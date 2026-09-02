# -*- coding: utf-8 -*-
"""首页工作台 API（M5，项目书 7.2）：六张卡片聚合（跨账套）。

DoD：仪表盘总览模式跨账套聚合正确；每张卡片可点击穿透到对应列表页。
"""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..modules.account.models import AccountMove
from ..modules.base.models import ResUsers
from ..modules.contract.models import ContractFeeItem
from ..modules.invoice.models import InvoiceBill
from ..modules.res_partner.models import ResBook
from ..modules.tax_decl.models import TaxDeclItem
from ..modules.tasks import service as tasks_service
from .deps import require_login

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def _month_range(period: str) -> tuple[date, date]:
    y, m = int(period[:4]), int(period[5:7])
    start = date(y, m, 1)
    if m == 12:
        end = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(y, m + 1, 1) - timedelta(days=1)
    return start, end


def _d(v) -> str:
    if isinstance(v, Decimal):
        return str(v.quantize(Decimal("0.01")))
    return str(v or 0)


@router.get("/summary")
def summary(month: str | None = Query(None, description="YYYY-MM，默认本月"),
            user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    today = date.today()
    period = month or f"{today.year:04d}-{today.month:02d}"
    start, end = _month_range(period)

    # ---------- 1. 本月概览 ----------
    books = db.execute(
        select(ResBook).where(ResBook.active.is_(True),
                              ResBook.charge_status != "terminated")
    ).scalars().all()
    total_books = len(books)
    normal_books = sum(1 for b in books if b.charge_status == "normal")

    draft_moves = db.execute(
        select(func.count()).select_from(AccountMove).where(
            AccountMove.active.is_(True), AccountMove.is_template.is_(False),
            AccountMove.period == period, AccountMove.state == "draft")
    ).scalar_one()
    posted_moves = db.execute(
        select(func.count()).select_from(AccountMove).where(
            AccountMove.active.is_(True), AccountMove.is_template.is_(False),
            AccountMove.period == period, AccountMove.state == "posted")
    ).scalar_one()
    new_invoices = db.execute(
        select(func.count()).select_from(InvoiceBill).where(
            InvoiceBill.active.is_(True), InvoiceBill.period == period)
    ).scalar_one()

    overview = {
        "total_books": total_books, "normal_books": normal_books,
        "draft_moves": draft_moves, "posted_moves": posted_moves,
        "new_invoices": new_invoices,
    }

    # ---------- 2. 申报日历红牌（未来 7 天到期且待办） ----------
    decl_alert = []
    for it in db.execute(
        select(TaxDeclItem).where(
            TaxDeclItem.active.is_(True),
            TaxDeclItem.due_date >= today,
            TaxDeclItem.due_date <= today + timedelta(days=7),
            TaxDeclItem.state.in_(["pending", "preparing"]),
        ).order_by(TaxDeclItem.due_date, TaxDeclItem.book_id).limit(30)
    ).scalars().all():
        book = db.get(ResBook, it.book_id)
        decl_alert.append({
            "id": it.id, "book_id": it.book_id,
            "book_name": book.short_name if book else None,
            "tax_kind": it.tax_kind, "period": it.period,
            "due_date": it.due_date.isoformat() if it.due_date else None,
            "state": it.state,
        })

    # ---------- 3. 逾期预警 ----------
    overdue_decl = db.execute(
        select(func.count()).select_from(TaxDeclItem).where(
            TaxDeclItem.active.is_(True), TaxDeclItem.due_date < today,
            TaxDeclItem.state.in_(["pending", "preparing"]))
    ).scalar_one()
    overdue_fee = db.execute(
        select(func.count()).select_from(ContractFeeItem).where(
            ContractFeeItem.active.is_(True), ContractFeeItem.due_date < today,
            ContractFeeItem.state.in_(["unpaid", "invoiced", "overdue"]))
    ).scalar_one()

    # ---------- 4. 待办任务（前 10 条） ----------
    # 先按状态过滤（todo/doing），再由 list_tasks 按 优先级→到期日 排序后取前 10，
    # 避免无到期日的普通任务被大量到期催收任务挤出 top 10。
    todo_tasks = [
        tasks_service.task_to_dict(db, t)
        for t in tasks_service.list_tasks(db, None, states=["todo", "doing"], limit=10)
    ]

    # ---------- 5. 收款月历（本月应收/已收/未收） ----------
    fee_rows = db.execute(
        select(ContractFeeItem).where(
            ContractFeeItem.active.is_(True),
            ContractFeeItem.due_date >= start, ContractFeeItem.due_date <= end)
    ).scalars().all()
    fee_receivable = sum((it.amount for it in fee_rows), Decimal("0"))
    fee_received = sum((it.paid_amount or it.amount for it in fee_rows
                        if it.state == "paid"), Decimal("0"))
    fee_unpaid = fee_receivable - fee_received

    # ---------- 6. 各客户进度（客户 × 本月 收票/凭证/申报/收费） ----------
    # 一次拉本月各业务明细，按 book_id 归组，避免 100 家客户 N+1。
    inv_by_book: dict[int, int] = {}
    for bid, cnt in db.execute(
        select(InvoiceBill.book_id, func.count()).where(
            InvoiceBill.active.is_(True), InvoiceBill.period == period)
        .group_by(InvoiceBill.book_id)
    ).all():
        inv_by_book[bid] = cnt

    posted_by_book: dict[int, int] = {}
    draft_by_book: dict[int, int] = {}
    for bid, state, cnt in db.execute(
        select(AccountMove.book_id, AccountMove.state, func.count()).where(
            AccountMove.active.is_(True), AccountMove.is_template.is_(False),
            AccountMove.period == period)
        .group_by(AccountMove.book_id, AccountMove.state)
    ).all():
        (posted_by_book if state == "posted" else draft_by_book)[bid] = cnt

    decl_by_book: dict[int, tuple[int, int]] = {}
    for bid, state, cnt in db.execute(
        select(TaxDeclItem.book_id, TaxDeclItem.state, func.count()).where(
            TaxDeclItem.active.is_(True),
            TaxDeclItem.due_date >= start, TaxDeclItem.due_date <= end)
        .group_by(TaxDeclItem.book_id, TaxDeclItem.state)
    ).all():
        total, done = decl_by_book.get(bid, (0, 0))
        total += cnt
        if state in ("submitted", "paid", "done", "exempt"):
            done += cnt
        decl_by_book[bid] = (total, done)

    fee_by_book: dict[int, tuple[int, int]] = {}
    for bid, state, cnt in db.execute(
        select(ContractFeeItem.book_id, ContractFeeItem.state, func.count()).where(
            ContractFeeItem.active.is_(True),
            ContractFeeItem.due_date >= start, ContractFeeItem.due_date <= end)
        .group_by(ContractFeeItem.book_id, ContractFeeItem.state)
    ).all():
        total, done = fee_by_book.get(bid, (0, 0))
        total += cnt
        if state == "paid":
            done += cnt
        fee_by_book[bid] = (total, done)

    progress = []
    for b in sorted(books, key=lambda x: x.code):
        bid = b.id
        inv = inv_by_book.get(bid, 0)
        posted = posted_by_book.get(bid, 0)
        draft = draft_by_book.get(bid, 0)
        d_total, d_done = decl_by_book.get(bid, (0, 0))
        f_total, f_done = fee_by_book.get(bid, (0, 0))

        def light(kind, total, done):
            # 状态灯：绿=完成 / 黄=有进行中或未完成 / 灰=本月无此项
            if total == 0:
                return "none"
            if done >= total:
                return "done"
            return "pending"

        progress.append({
            "book_id": bid, "code": b.code, "short_name": b.short_name,
            "invoice": {"count": inv, "light": "done" if inv > 0 else "none"},
            "move": {"posted": posted, "draft": draft,
                     "light": "done" if posted > 0 else ("pending" if draft > 0 else "none")},
            "decl": {"total": d_total, "done": d_done, "light": light("decl", d_total, d_done)},
            "fee": {"total": f_total, "done": f_done, "light": light("fee", f_total, f_done)},
        })

    return {
        "month": period,
        "overview": overview,
        "decl_alert": decl_alert,
        "overdue": {"decl": overdue_decl, "fee": overdue_fee},
        "todo_tasks": todo_tasks,
        "fee_month": {
            "receivable": _d(fee_receivable),
            "received": _d(fee_received),
            "unpaid": _d(fee_unpaid),
        },
        "progress": progress,
    }
