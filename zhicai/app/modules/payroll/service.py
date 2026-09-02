# -*- coding: utf-8 -*-
"""payroll 业务逻辑（项目书 7.11）：批次 / 员工行 / 个税计算 / 确认生成凭证。

凭证口径（小企业准则，科目表 6.12 预置）：
- 计提凭证：借 6602.07 工资 total_gross、借 6602.08 社保公积金（单位社保+单位公积金）；
            贷 2211.01 工资 total_gross、贷 2211.02 社保公积金（同单位部分）
- 发放凭证：借 2211.01 工资 total_gross；
            贷 1002 银行存款 total_net、贷 2211.02 个人社保、贷 2221.04 应交个税
  平衡依据：net = gross − 个人社保 − 个税
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ..account import move_service
from ..account.models import AccountAccount, AccountJournal
from ..res_partner.models import ResBook
from . import iit
from .models import PayrollBatch, PayrollLine

ZERO = Decimal("0.00")


def _dec(v) -> Decimal:
    if v is None or v == "":
        return ZERO
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return ZERO


def _d(v) -> str:
    return str(_dec(v).quantize(Decimal("0.01")))


def lines_of(db: Session, batch_id: int) -> list[PayrollLine]:
    return db.execute(
        select(PayrollLine)
        .where(PayrollLine.batch_id == batch_id, PayrollLine.active.is_(True))
        .order_by(PayrollLine.id)
    ).scalars().all()


def recalc_batch(db: Session, batch: PayrollBatch) -> None:
    """按员工行重算批次合计。"""
    lines = lines_of(db, batch.id)
    batch.employee_count = len(lines)
    batch.total_gross = sum((l.gross_salary for l in lines), ZERO)
    batch.total_net = sum((l.net_salary for l in lines), ZERO)
    batch.social_base = sum((l.social_employee + l.social_employer for l in lines), ZERO)
    db.flush()


def create_batch(db: Session, *, book_id: int, period: str,
                 remark: str | None = None, user_id: int | None = None,
                 copy_from_last: bool = False) -> PayrollBatch:
    """按月建批次；每账套每期间唯一。copy_from_last=True 时复制上月员工行（金额可改）。"""
    if not _valid_period(period):
        raise BizError("period_invalid", "期间格式应为 YYYY-MM")
    dup = db.execute(
        select(PayrollBatch.id).where(
            PayrollBatch.book_id == book_id, PayrollBatch.period == period,
            PayrollBatch.active.is_(True))
    ).scalar_one_or_none()
    if dup is not None:
        raise BizError("batch_dup", f"{period} 的工资批次已存在（每账套每期间一份）")

    now = datetime.now()
    batch = PayrollBatch(
        book_id=book_id, period=period, state="draft",
        remark=remark or None,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
    )
    db.add(batch)
    db.flush()

    if copy_from_last:
        copied = copy_from_last_month(db, batch, user_id)
        batch.remark = remark or None
        if copied:
            recalc_iit(db, batch)
    db.flush()
    return batch


def _valid_period(period: str) -> bool:
    try:
        y, m = int(period[:4]), int(period[5:7])
        return 1 <= m <= 12 and len(period) == 7
    except Exception:
        return False


def _prev_period(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    if m == 1:
        return f"{y - 1:04d}-12"
    return f"{y:04d}-{m - 1:02d}"


def copy_from_last_month(db: Session, batch: PayrollBatch,
                         user_id: int | None = None) -> int:
    """复制上月批次的员工行（含社保公积金结构，个税重算）。返回复制条数。"""
    prev = db.execute(
        select(PayrollBatch).where(
            PayrollBatch.book_id == batch.book_id, PayrollBatch.period == _prev_period(batch.period),
            PayrollBatch.active.is_(True))
    ).scalar_one_or_none()
    if prev is None:
        return 0
    now = datetime.now()
    created = 0
    for ln in lines_of(db, prev.id):
        db.add(PayrollLine(
            batch_id=batch.id, book_id=batch.book_id,
            employee_name=ln.employee_name, id_card_tail=ln.id_card_tail,
            gross_salary=ln.gross_salary, social_employee=ln.social_employee,
            social_employer=ln.social_employer, fund_employer=ln.fund_employer,
            iit=ZERO, net_salary=ZERO, remark=ln.remark,
            create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
        ))
        created += 1
    if created:
        db.flush()
        recalc_iit(db, batch)
    return created


def add_line(db: Session, batch: PayrollBatch, data: dict,
             user_id: int | None = None) -> PayrollLine:
    if batch.state != "draft":
        raise BizError("batch_not_draft", "批次已确认，员工行不可修改（如需调整请另建批次或联系管理员处理）")
    name = (data.get("employee_name") or "").strip()
    if not name:
        raise BizError("name_required", "员工姓名不能为空")
    gross = _dec(data.get("gross_salary"))
    if gross < 0:
        raise BizError("amount_negative", "应发工资不能为负数")
    now = datetime.now()
    line = PayrollLine(
        batch_id=batch.id, book_id=batch.book_id,
        employee_name=name,
        id_card_tail=(data.get("id_card_tail") or "").strip()[-4:] or None,
        gross_salary=gross,
        social_employee=_dec(data.get("social_employee")),
        social_employer=_dec(data.get("social_employer")),
        fund_employer=_dec(data.get("fund_employer")),
        iit=_dec(data.get("iit")) if data.get("iit") is not None else ZERO,
        net_salary=ZERO,
        remark=data.get("remark") or None,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
    )
    db.add(line)
    db.flush()
    if data.get("iit") is None:
        # 未显式给个税 → 自动算
        line.iit = iit.compute_iit_monthly(line.gross_salary, line.social_employee)
    line.net_salary = (line.gross_salary - line.social_employee - line.iit).quantize(Decimal("0.01"))
    db.flush()
    recalc_batch(db, batch)
    return line


def update_line(db: Session, line_id: int, data: dict,
                user_id: int | None = None) -> PayrollLine:
    line = db.get(PayrollLine, line_id)
    if line is None or not line.active:
        raise BizError("not_found", "员工行不存在")
    batch = db.get(PayrollBatch, line.batch_id)
    if batch.state != "draft":
        raise BizError("batch_not_draft", "批次已确认，员工行不可修改")
    if data.get("employee_name"):
        line.employee_name = data["employee_name"].strip()
    if "id_card_tail" in data:
        line.id_card_tail = (data["id_card_tail"] or "").strip()[-4:] or None
    for f in ("gross_salary", "social_employee", "social_employer", "fund_employer"):
        if f in data:
            v = _dec(data[f])
            if v < 0:
                raise BizError("amount_negative", f"{f} 不能为负数")
            setattr(line, f, v)
    if "remark" in data:
        line.remark = data["remark"] or None
    if "iit" in data:
        line.iit = _dec(data["iit"]) if data["iit"] is not None else \
            iit.compute_iit_monthly(line.gross_salary, line.social_employee)
    line.net_salary = (line.gross_salary - line.social_employee - line.iit).quantize(Decimal("0.01"))
    line.write_uid = user_id
    line.write_date = datetime.now()
    db.flush()
    recalc_batch(db, batch)
    return line


def delete_line(db: Session, line_id: int, user_id: int | None = None) -> None:
    line = db.get(PayrollLine, line_id)
    if line is None or not line.active:
        raise BizError("not_found", "员工行不存在")
    batch = db.get(PayrollBatch, line.batch_id)
    if batch.state != "draft":
        raise BizError("batch_not_draft", "批次已确认，员工行不可删除")
    line.active = False
    line.write_uid = user_id
    line.write_date = datetime.now()
    db.flush()
    recalc_batch(db, batch)


def recalc_iit(db: Session, batch: PayrollBatch) -> int:
    """重算批次全部员工个税与实发（覆盖手工值）。"""
    if batch.state != "draft":
        raise BizError("batch_not_draft", "批次已确认，不能重算")
    count = 0
    for ln in lines_of(db, batch.id):
        ln.iit = iit.compute_iit_monthly(ln.gross_salary, ln.social_employee)
        ln.net_salary = (ln.gross_salary - ln.social_employee - ln.iit).quantize(Decimal("0.01"))
        count += 1
    db.flush()
    recalc_batch(db, batch)
    return count


# ==================== 确认 → 生成凭证 ====================

def _find_account(db: Session, book_id: int, code: str) -> AccountAccount:
    acc = db.execute(
        select(AccountAccount).where(
            AccountAccount.book_id == book_id, AccountAccount.code == code,
            AccountAccount.active.is_(True))
    ).scalar_one_or_none()
    if acc is None:
        raise BizError("account_missing", f"科目 {code} 不存在，请先补齐科目表")
    return acc


def _find_journal(db: Session, book_id: int, code: str = "记") -> AccountJournal:
    journal = db.execute(
        select(AccountJournal).where(
            AccountJournal.book_id == book_id, AccountJournal.code == code,
            AccountJournal.active.is_(True))
    ).scalar_one_or_none()
    if journal is None:
        raise BizError("journal_missing", f"凭证字 {code} 不存在")
    return journal


def confirm_batch(db: Session, batch_id: int, user_id: int | None = None,
                  move_date: date | None = None) -> PayrollBatch:
    """确认批次：生成计提 + 发放两张 draft 凭证（不自动过账，留人工复核）。"""
    batch = db.get(PayrollBatch, batch_id)
    if batch is None or not batch.active:
        raise BizError("not_found", "工资批次不存在")
    if batch.state != "draft":
        raise BizError("batch_confirmed", "批次已确认，不能重复确认")
    lines = lines_of(db, batch_id)
    if not lines:
        raise BizError("batch_empty", "批次没有员工行，不能确认")
    recalc_batch(db, batch)

    book = db.get(ResBook, batch.book_id)
    mdate = move_date or date(int(batch.period[:4]), int(batch.period[5:7]), 28)
    journal = _find_journal(db, batch.book_id, "记")
    acc_salary_exp = _find_account(db, batch.book_id, "6602.07")
    acc_social_exp = _find_account(db, batch.book_id, "6602.08")
    acc_payroll = _find_account(db, batch.book_id, "2211.01")
    acc_social_pay = _find_account(db, batch.book_id, "2211.02")
    acc_iit = _find_account(db, batch.book_id, "2221.04")
    acc_bank = _find_account(db, batch.book_id, "1002")

    total_gross = _dec(batch.total_gross)
    total_net = _dec(batch.total_net)
    social_employee = sum((l.social_employee for l in lines), ZERO)
    social_employer = sum((l.social_employer for l in lines), ZERO)
    fund_employer = sum((l.fund_employer for l in lines), ZERO)
    total_iit = sum((l.iit for l in lines), ZERO)
    employer_total = social_employer + fund_employer
    period_label = f"{batch.period} 工资"

    # ---- 计提凭证 ----
    accrual_lines = [
        {"summary": f"计提{period_label}", "account_id": acc_salary_exp.id,
         "debit": str(total_gross), "credit": "0"},
    ]
    if employer_total > 0:
        accrual_lines.append({
            "summary": f"计提{batch.period}社保公积金（单位）",
            "account_id": acc_social_exp.id, "debit": str(employer_total), "credit": "0"})
    accrual_lines.append({
        "summary": f"计提{period_label}", "account_id": acc_payroll.id,
        "debit": "0", "credit": str(total_gross)})
    if employer_total > 0:
        accrual_lines.append({
            "summary": f"计提{batch.period}社保公积金（单位）", "account_id": acc_social_pay.id,
            "debit": "0", "credit": str(employer_total)})
    accrual = move_service.create_move(
        db, book_id=batch.book_id, journal_id=journal.id, move_date=mdate,
        lines=accrual_lines, source_type="payroll", user_id=user_id,
        remark=f"{period_label} 计提（批次 #{batch.id}）")

    # ---- 发放凭证 ----
    payment_lines = [
        {"summary": f"发放{period_label}", "account_id": acc_payroll.id,
         "debit": str(total_gross), "credit": "0"},
        {"summary": f"发放{period_label}（实发）", "account_id": acc_bank.id,
         "debit": "0", "credit": str(total_net)},
    ]
    if social_employee > 0:
        payment_lines.append({
            "summary": f"代扣{batch.period}个人社保", "account_id": acc_social_pay.id,
            "debit": "0", "credit": str(social_employee)})
    if total_iit > 0:
        payment_lines.append({
            "summary": f"代扣{batch.period}个税", "account_id": acc_iit.id,
            "debit": "0", "credit": str(total_iit)})
    payment = move_service.create_move(
        db, book_id=batch.book_id, journal_id=journal.id, move_date=mdate,
        lines=payment_lines, source_type="payroll", user_id=user_id,
        remark=f"{period_label} 发放（批次 #{batch.id}）")

    batch.accrual_move_id = accrual.id
    batch.payment_move_id = payment.id
    batch.state = "confirmed"
    batch.write_uid = user_id
    batch.write_date = datetime.now()
    db.flush()
    return batch


def mark_paid(db: Session, batch_id: int, user_id: int | None = None) -> PayrollBatch:
    batch = db.get(PayrollBatch, batch_id)
    if batch is None or not batch.active:
        raise BizError("not_found", "工资批次不存在")
    if batch.state != "confirmed":
        raise BizError("state_invalid", "只有已确认的批次可标记已发放")
    batch.state = "paid"
    batch.write_uid = user_id
    batch.write_date = datetime.now()
    db.flush()
    return batch


def batch_to_dict(db: Session, b: PayrollBatch, with_lines: bool = False) -> dict:
    book = db.get(ResBook, b.book_id)
    out = {
        "id": b.id, "book_id": b.book_id,
        "book_name": book.short_name if book else None,
        "period": b.period, "state": b.state,
        "employee_count": b.employee_count,
        "total_gross": _d(b.total_gross), "total_net": _d(b.total_net),
        "social_base": _d(b.social_base),
        "accrual_move_id": b.accrual_move_id, "payment_move_id": b.payment_move_id,
        "remark": b.remark,
    }
    if with_lines:
        out["lines"] = [line_to_dict(ln) for ln in lines_of(db, b.id)]
    return out


def line_to_dict(ln: PayrollLine) -> dict:
    return {
        "id": ln.id, "batch_id": ln.batch_id, "employee_name": ln.employee_name,
        "id_card_tail": ln.id_card_tail,
        "gross_salary": _d(ln.gross_salary), "social_employee": _d(ln.social_employee),
        "social_employer": _d(ln.social_employer), "fund_employer": _d(ln.fund_employer),
        "iit": _d(ln.iit), "net_salary": _d(ln.net_salary), "remark": ln.remark,
    }
