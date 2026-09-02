# -*- coding: utf-8 -*-
"""contract 模块业务逻辑（项目书 7.4）：收费计划生成 / 收款登记 / 应收统计 / 逾期与续约扫描。"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ..res_partner.models import ResBook
from ..tasks.models import TaskTask
from .models import ContractAgreement, ContractFeeItem


def _periods_of(agreement: ContractAgreement) -> list[tuple[str, date]]:
    """按合同收费周期，展开 [start_date, end_date] 内的所有收费期。

    返回 [(period, due_date), ...]；period 格式：月 YYYY-MM / 季 YYYYQn / 年 YYYY。
    due_date 取该期第一天（期初应付）。
    """
    start, end = agreement.start_date, agreement.end_date
    out: list[tuple[str, date]] = []
    ft = agreement.fee_type

    if ft == "monthly":
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            out.append((f"{y:04d}-{m:02d}", date(y, m, 1)))
            m += 1
            if m > 12:
                m, y = 1, y + 1
    elif ft == "quarterly":
        y, q = start.year, (start.month - 1) // 3 + 1
        ey, eq = end.year, (end.month - 1) // 3 + 1
        while (y, q) <= (ey, eq):
            out.append((f"{y:04d}Q{q}", date(y, (q - 1) * 3 + 1, 1)))
            q += 1
            if q > 4:
                q, y = 1, y + 1
    else:  # annual
        for y in range(start.year, end.year + 1):
            out.append((f"{y:04d}", date(y, 1, 1)))
    return out


def generate_fee_items(db: Session, agreement: ContractAgreement) -> dict:
    """按合同周期生成收费计划（幂等：已存在同 (agreement, period) 则跳过）。"""
    if agreement.state == "terminated":
        raise BizError("contract_terminated", "合同已终止，不能生成收费计划")
    existing = {
        p for (p,) in db.execute(
            select(ContractFeeItem.period).where(
                ContractFeeItem.agreement_id == agreement.id,
                ContractFeeItem.active.is_(True),
            )
        ).all()
    }
    created = 0
    for period, due_date in _periods_of(agreement):
        if period in existing:
            continue
        db.add(ContractFeeItem(
            agreement_id=agreement.id, book_id=agreement.book_id,
            period=period, amount=agreement.fee_amount, due_date=due_date,
            state="unpaid", active=True,
        ))
        created += 1
    if created:
        db.flush()
    return {"created": created, "skipped": len(existing),
            "periods": [p for p, _ in _periods_of(agreement)]}


def collect_fee_items(db: Session, fee_item_ids: list[int], *,
                      paid_date: date | None = None,
                      paid_amounts: dict[int, str] | None = None) -> dict:
    """批量收款登记：把多条收费计划标记为已收款（paid）。

    paid_amounts: {fee_item_id: 金额字符串}，缺省按该期应收金额。
    """
    if not fee_item_ids:
        raise BizError("empty_selection", "未选择任何收费计划")
    today = date.today()
    rows = db.execute(
        select(ContractFeeItem).where(
            ContractFeeItem.id.in_(fee_item_ids),
            ContractFeeItem.active.is_(True),
        )
    ).scalars().all()
    if not rows:
        raise BizError("not_found", "未找到有效收费计划")
    collected = 0
    for it in rows:
        if it.state == "paid":
            continue
        it.state = "paid"
        it.paid_date = paid_date or today
        raw = (paid_amounts or {}).get(it.id)
        it.paid_amount = Decimal(str(raw)) if raw is not None else it.amount
        collected += 1
    db.flush()
    return {"collected": collected, "total": len(rows)}


def mark_invoiced(db: Session, fee_item_id: int, invoice_no: str | None = None) -> ContractFeeItem:
    """标记已开票。"""
    it = db.get(ContractFeeItem, fee_item_id)
    if it is None or not it.active:
        raise BizError("not_found", "收费计划不存在")
    it.state = "invoiced"
    if invoice_no:
        it.invoice_no = invoice_no
    db.flush()
    return it


def receivable_report(db: Session, book_id: int | None = None) -> dict:
    """应收统计：按客户 / 按月份 + 本年度已收合计（项目书 7.4）。"""
    q = select(ContractFeeItem).where(ContractFeeItem.active.is_(True))
    if book_id:
        q = q.where(ContractFeeItem.book_id == book_id)
    rows = db.execute(q).scalars().all()

    today = date.today()
    by_book: dict[int, dict] = {}
    by_month: dict[str, dict] = {}
    year_received = Decimal("0")

    for it in rows:
        key = it.book_id
        b = by_book.setdefault(key, {"book_id": key, "receivable": Decimal("0"),
                                     "received": Decimal("0"), "overdue": Decimal("0")})
        b["receivable"] += it.amount
        if it.state == "paid":
            b["received"] += it.paid_amount or it.amount
            if it.paid_date and it.paid_date.year == today.year:
                year_received += it.paid_amount or it.amount
        elif it.is_overdue:
            b["overdue"] += it.amount

        if it.period:
            mk = it.period
            m = by_month.setdefault(mk, {"period": mk, "receivable": Decimal("0"),
                                         "received": Decimal("0"), "overdue": Decimal("0")})
            m["receivable"] += it.amount
            if it.state == "paid":
                m["received"] += it.paid_amount or it.amount
            elif it.is_overdue:
                m["overdue"] += it.amount

    # 挂客户名
    books = {
        b.id: b.short_name for b in db.execute(
            select(ResBook).where(ResBook.id.in_(list(by_book.keys())))
        ).scalars().all() if by_book
    }
    book_list = sorted(
        ({**v, "book_name": books.get(v["book_id"], f"#{v['book_id']}")}
         for v in by_book.values()),
        key=lambda x: x["book_name"],
    )
    month_list = sorted(by_month.values(), key=lambda x: x["period"])

    def _s(d: Decimal) -> str:
        return str(d.quantize(Decimal("0.01")))

    return {
        "by_book": [{k: (_s(v) if k != "book_id" and k != "book_name" else v)
                     for k, v in row.items()} for row in book_list],
        "by_month": [{k: (_s(v) if k != "period" else v) for k, v in row.items()}
                     for row in month_list],
        "year_received": _s(year_received),
    }


def _ensure_task(db: Session, title: str, *, book_id: int | None,
                 source_model: str, source_id: int, due_date: date | None,
                 priority: str = "high", description: str | None = None) -> bool:
    """按 source 幂等建任务：同 source 且未完成/未取消的已存在则跳过。"""
    existed = db.execute(
        select(TaskTask.id).where(
            TaskTask.source_model == source_model,
            TaskTask.source_id == source_id,
            TaskTask.active.is_(True),
            TaskTask.state.in_(["todo", "doing"]),
        )
    ).scalar_one_or_none()
    if existed is not None:
        return False
    db.add(TaskTask(
        book_id=book_id, title=title, description=description,
        due_date=due_date, priority=priority, state="todo",
        source_model=source_model, source_id=source_id,
        reminder_sent=False, active=True,
    ))
    return True


def scan_overdue_and_renewal(db: Session, user_id: int | None = None) -> dict:
    """逾期扫描 + 到期前 30 天续约提醒（项目书 7.4 / 7.13 fee_overdue 任务）。

    - 未收款（unpaid/invoiced）且已过到期日 → 标 overdue + 生成催收任务；
    - 履行中合同距结束日 ≤ 30 天 → 生成续约提醒任务。
    幂等：已存在未完成的同 source 任务不再重复生成。
    """
    today = date.today()
    books = {b.id: b for b in db.execute(select(ResBook)).scalars().all()}

    overdue_marked = 0
    collection_created = 0
    for it in db.execute(
        select(ContractFeeItem).where(
            ContractFeeItem.active.is_(True),
            ContractFeeItem.state.in_(["unpaid", "invoiced"]),
            ContractFeeItem.due_date < today,
        )
    ).scalars().all():
        if it.state != "overdue":
            it.state = "overdue"
            overdue_marked += 1
        book = books.get(it.book_id)
        bname = book.short_name if book else f"#{it.book_id}"
        if _ensure_task(
            db, f"催收代账费：{bname} {it.period} ¥{it.amount}",
            book_id=it.book_id, source_model="contract_fee_item", source_id=it.id,
            due_date=today, priority="high",
            description=f"客户 {bname} 的 {it.period} 期代账费已逾期，金额 ¥{it.amount}",
        ):
            collection_created += 1

    renewal_created = 0
    for ag in db.execute(
        select(ContractAgreement).where(
            ContractAgreement.active.is_(True),
            ContractAgreement.state == "active",
            ContractAgreement.end_date >= today,
            ContractAgreement.end_date <= today + timedelta(days=30),
        )
    ).scalars().all():
        book = books.get(ag.book_id)
        bname = book.short_name if book else f"#{ag.book_id}"
        if _ensure_task(
            db, f"合同续约提醒：{bname} 合同 {ag.contract_no} 将于 {ag.end_date} 到期",
            book_id=ag.book_id, source_model="contract_agreement", source_id=ag.id,
            due_date=ag.end_date - timedelta(days=15), priority="high",
            description=f"客户 {bname} 的代账合同 {ag.contract_no} 即将到期，请及时续约",
        ):
            renewal_created += 1

    db.flush()
    return {"overdue_marked": overdue_marked, "collection_tasks": collection_created,
            "renewal_tasks": renewal_created}
