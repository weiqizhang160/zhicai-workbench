# -*- coding: utf-8 -*-
"""凭证服务层：创建/编辑/过账/红冲/期间锁（项目书 6.5 约束 + 7.5 界面行为）。

对标 Odoo account.move 的 posting 约束：
- 过账前校验：借贷平衡、总额>0、行数≥2、借贷互斥、摘要/科目必填、科目末级、期间未锁；
- posted 后整单只读，唯一出路是红冲；
- draft 可任意编辑/删除。
"""
import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ...core.sequence import ensure_sequence, next_number
from .models import (
    AccountAccount,
    AccountJournal,
    AccountMove,
    AccountMoveLine,
    AccountPeriodClose,
)

ZERO = Decimal("0.00")

# 期末结转：损益类一级科目代码（项目书 7.5），其下所有末级科目余额结转至本年利润
PL_ACCOUNT_CODES = (
    "6001", "6051", "6111", "6301",          # 收入类
    "6401", "6402", "6403",                   # 成本类
    "6601", "6602", "6603",                   # 费用类
    "6711", "6801",                           # 营业外支出 / 所得税费用
)
PROFIT_ACCOUNT_CODE = "3103"                  # 本年利润


def _dec(v) -> Decimal:
    """统一转 Decimal（前端传字符串，DB 读回也是 Decimal）。"""
    if v is None or v == "":
        return ZERO
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def period_of(d: date) -> str:
    """日期 → 期间 YYYY-MM。"""
    return f"{d.year:04d}-{d.month:02d}"


def _aux_flags(acc: AccountAccount) -> dict:
    """解析科目辅助核算标志 JSON（损坏时返回空，不抛错）。"""
    raw = getattr(acc, "auxiliary_flags", None)
    if not raw:
        return {}
    try:
        return json.loads(raw) or {}
    except (ValueError, TypeError):
        return {}


# ==================== 期间锁 ====================

def is_period_closed(db: Session, book_id: int, period: str) -> bool:
    row = db.execute(
        select(AccountPeriodClose).where(
            AccountPeriodClose.book_id == book_id,
            AccountPeriodClose.period == period,
            AccountPeriodClose.active.is_(True),
        )
    ).scalar_one_or_none()
    return bool(row and row.closed)


def assert_period_open(db: Session, book_id: int, period: str, action: str = "操作"):
    if is_period_closed(db, book_id, period):
        raise BizError("period_closed", f"期间 {period} 已结账锁定，无法{action}。如需补录请先在「期末结账」解锁该期间")


def close_period(db: Session, book_id: int, period: str, user_id: int | None = None,
                 note: str | None = None) -> AccountPeriodClose:
    """结账（锁定期间）。"""
    row = db.execute(
        select(AccountPeriodClose).where(
            AccountPeriodClose.book_id == book_id, AccountPeriodClose.period == period)
    ).scalar_one_or_none()
    if row is None:
        row = AccountPeriodClose(book_id=book_id, period=period, closed=False,
                                 create_uid=user_id, create_date=datetime.now(), active=True)
        db.add(row)
    if row.closed:
        raise BizError("period_already_closed", f"期间 {period} 已经是结账状态")
    row.closed = True
    row.closed_at = datetime.now()
    row.note = note
    row.write_uid = user_id
    row.write_date = datetime.now()
    db.flush()
    return row


def open_period(db: Session, book_id: int, period: str, user_id: int | None = None) -> AccountPeriodClose:
    """解锁期间（跨期补录用，会留审计）。"""
    row = db.execute(
        select(AccountPeriodClose).where(
            AccountPeriodClose.book_id == book_id, AccountPeriodClose.period == period)
    ).scalar_one_or_none()
    if row is None or not row.closed:
        raise BizError("period_not_closed", f"期间 {period} 未处于结账状态，无需解锁")
    row.closed = False
    row.closed_at = None
    row.write_uid = user_id
    row.write_date = datetime.now()
    db.flush()
    return row


# ==================== 凭证与分录读写 ====================

def lines_of(db: Session, move_id: int) -> list[AccountMoveLine]:
    return db.execute(
        select(AccountMoveLine)
        .where(AccountMoveLine.move_id == move_id, AccountMoveLine.active.is_(True))
        .order_by(AccountMoveLine.line_no)
    ).scalars().all()


def get_move(db: Session, move_id: int) -> AccountMove:
    move = db.get(AccountMove, move_id)
    if move is None or not move.active:
        raise BizError("move_not_found", "凭证不存在或已删除")
    return move


def _apply_line(line: AccountMoveLine, data: dict, book_id: int, now: datetime):
    line.summary = (data.get("summary") or "").strip()
    line.account_id = data.get("account_id")
    line.partner_id = data.get("partner_id")
    line.department = data.get("department") or None
    line.project = data.get("project") or None
    line.debit = _dec(data.get("debit"))
    line.credit = _dec(data.get("credit"))
    line.book_id = book_id


def create_move(db: Session, *, book_id: int, journal_id: int, move_date: date,
                lines: list[dict], attachment_count: int = 0, remark: str | None = None,
                source_type: str = "manual", user_id: int | None = None,
                is_template: bool = False, template_name: str | None = None) -> AccountMove:
    """新建凭证（含分录），状态为 draft。"""
    if journal_id is None:
        raise BizError("journal_required", "请选择凭证字")
    if db.get(AccountJournal, journal_id) is None:
        raise BizError("journal_not_found", "凭证字不存在")

    period = period_of(move_date)
    if not is_template:  # 模板不参与账务，不受期间锁约束
        assert_period_open(db, book_id, period, "新增凭证")

    now = datetime.now()
    move = AccountMove(
        journal_id=journal_id, move_date=move_date, period=period, state="draft",
        source_type=source_type, attachment_count=attachment_count or 0, remark=remark,
        is_template=is_template, template_name=template_name, book_id=book_id,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
    )
    db.add(move)
    db.flush()  # 拿 move.id

    _replace_lines(db, move, lines, book_id, user_id)
    db.flush()
    return move


def _replace_lines(db: Session, move: AccountMove, lines: list[dict], book_id: int,
                   user_id: int | None = None):
    """整单替换分录（draft 可任意编辑）。"""
    now = datetime.now()
    # 旧行软删除
    for old in lines_of(db, move.id):
        old.active = False
        old.write_uid = user_id
        old.write_date = now
    db.flush()
    for idx, data in enumerate(lines or [], start=1):
        line = AccountMoveLine(
            move_id=move.id, line_no=idx, book_id=book_id,
            create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
        )
        _apply_line(line, data, book_id, now)
        db.add(line)
    db.flush()


def update_move(db: Session, move_id: int, *, user_id: int | None = None, **fields) -> AccountMove:
    """编辑凭证（仅 draft 可编辑）。"""
    move = get_move(db, move_id)
    if not move.is_editable:
        raise BizError("move_readonly", "已过账的凭证不可修改，如需更正请红冲后重新录入")

    move_date = fields.get("move_date", move.move_date)
    new_period = period_of(move_date)
    assert_period_open(db, move.book_id, new_period, "修改凭证")

    move.journal_id = fields.get("journal_id", move.journal_id)
    move.move_date = move_date
    move.period = new_period
    move.attachment_count = fields.get("attachment_count", move.attachment_count)
    move.remark = fields.get("remark", move.remark)
    move.template_name = fields.get("template_name", move.template_name)
    move.write_uid = user_id
    move.write_date = datetime.now()

    if "lines" in fields and fields["lines"] is not None:
        _replace_lines(db, move, fields["lines"], move.book_id, user_id)
    db.flush()
    return move


def delete_move(db: Session, move_id: int, user_id: int | None = None) -> None:
    """删除凭证（仅 draft；posted 必须先红冲）。"""
    move = get_move(db, move_id)
    if not move.is_editable:
        raise BizError("move_readonly", "已过账的凭证不可删除，如需作废请红冲")
    assert_period_open(db, move.book_id, move.period, "删除凭证")
    now = datetime.now()
    for line in lines_of(db, move_id):
        line.active = False
        line.write_uid = user_id
        line.write_date = now
    move.active = False
    move.write_uid = user_id
    move.write_date = now
    db.flush()


# ==================== 过账校验（项目书 6.5 全部约束） ====================

def validate_for_post(db: Session, move: AccountMove, lines: list[AccountMoveLine]) -> None:
    """过账前全量校验，任一不满足即抛 BizError（单测覆盖每个分支）。"""
    if move.state != "draft":
        raise BizError("move_not_draft", "只有草稿状态的凭证可以过账")
    if move.is_template:
        raise BizError("template_not_postable", "常用凭证模板不参与账务，不能过账")
    if not lines or len(lines) < 2:
        raise BizError("move_lines_min", "凭证至少需要 2 行分录")
    assert_period_open(db, move.book_id, move.period, "过账")

    total_debit = ZERO
    total_credit = ZERO
    for ln in lines:
        no = ln.line_no
        # 摘要必填（中国凭证要素）
        if not (ln.summary or "").strip():
            raise BizError("summary_required", f"第 {no} 行：摘要不能为空")
        # 科目必填且必须末级
        if not ln.account_id:
            raise BizError("account_required", f"第 {no} 行：科目不能为空")
        acc = db.get(AccountAccount, ln.account_id)
        if acc is None:
            raise BizError("account_not_found", f"第 {no} 行：科目不存在")
        if not acc.is_leaf:
            raise BizError("account_not_leaf",
                           f"第 {no} 行：科目 {acc.code} {acc.name} 不是末级科目，不能记账")
        # 借贷互斥且不能为负
        d, c = _dec(ln.debit), _dec(ln.credit)
        if d < 0 or c < 0:
            raise BizError("amount_negative", f"第 {no} 行：金额不能为负数")
        if d > 0 and c > 0:
            raise BizError("amount_exclusive", f"第 {no} 行：借方与贷方不能同时填写金额")
        if d == 0 and c == 0:
            raise BizError("amount_empty", f"第 {no} 行：借方或贷方必须有一方填写金额")
        # 辅助核算：科目启用往来单位则必填。
        # 但仅约束「手工录入」凭证：期末结转这类系统生成的内部凭证无法也无必要
        # 拆分到往来单位维度（实务上结转凭证不带辅助核算），若强制会直接卡死结转。
        if move.source_type == "manual" and _aux_flags(acc).get("partner") and not ln.partner_id:
            raise BizError("partner_required",
                           f"第 {no} 行：科目 {acc.code} {acc.name} 启用了往来单位辅助核算，必须填写往来单位")
        total_debit += d
        total_credit += c

    if total_debit != total_credit:
        diff = total_debit - total_credit
        raise BizError("move_unbalanced",
                       f"借贷不平衡：借方合计 {total_debit}，贷方合计 {total_credit}，差额 {diff}")
    if total_debit <= 0:
        raise BizError("move_zero_amount", "凭证金额必须大于 0")


def _next_move_name(db: Session, book_id: int, journal_code: str, period: str) -> str:
    """生成凭证号：记-202609-0001（按账套 + 凭证字 + 月份重置）。"""
    yyyymm = period.replace("-", "")
    seq_code = f"move.{book_id}.{journal_code}"
    seq = ensure_sequence(db, seq_code, prefix=f"{journal_code}-", book_id=book_id, padding=4)
    # 让编号带年月：记-202609-0001
    seq.prefix = f"{journal_code}-{yyyymm}-"
    db.flush()
    return next_number(db, seq_code, book_id=book_id, period=yyyymm)


def post_move(db: Session, move_id: int, user_id: int | None = None) -> AccountMove:
    """过账：跑全部校验 → 生成凭证号 → state=posted。"""
    move = get_move(db, move_id)
    lines = lines_of(db, move_id)
    validate_for_post(db, move, lines)

    journal = db.get(AccountJournal, move.journal_id)
    move.name = _next_move_name(db, move.book_id, journal.code, move.period)
    move.state = "posted"
    move.write_uid = user_id
    move.write_date = datetime.now()
    db.flush()
    return move


def post_moves_bulk(db: Session, move_ids: list[int], user_id: int | None = None) -> dict:
    """批量过账：逐单执行，失败原因逐单记录（不中断其他单）。"""
    posted, failed = [], []
    for mid in move_ids:
        try:
            move = post_move(db, mid, user_id)
            posted.append({"id": move.id, "name": move.name})
        except BizError as e:
            db.rollback()
            failed.append({"id": mid, "code": e.code, "message": e.message})
    db.flush()
    return {"posted": posted, "failed": failed}


# ==================== 红冲 ====================

def reverse_move(db: Session, move_id: int, user_id: int | None = None,
                 reverse_date: date | None = None) -> AccountMove:
    """红冲已过账凭证：生成反向凭证（借贷互换、摘要加"红冲："），两单互链，原单 state=voided。

    红冲单记在当前日期所在期间（实务做法），因此不受原凭证期间锁定影响，但受当期期间锁约束。
    """
    move = get_move(db, move_id)
    # 先判是否已红冲过：原单红冲后 state 已变 voided，
    # 若先判 state 会误报"只有已过账的凭证可以红冲"，语义不准确
    if move.reversed_move_id:
        raise BizError("already_reversed", "该凭证已被红冲，不能重复红冲")
    if move.state != "posted":
        raise BizError("reverse_require_posted", "只有已过账的凭证可以红冲")

    src_lines = lines_of(db, move_id)
    rdate = reverse_date or date.today()
    rperiod = period_of(rdate)
    assert_period_open(db, move.book_id, rperiod, "红冲")

    now = datetime.now()
    new_move = AccountMove(
        journal_id=move.journal_id, move_date=rdate, period=rperiod, state="draft",
        source_type="reversal", attachment_count=move.attachment_count,
        remark=f"红冲 {move.name or ('#' + str(move.id))}",
        reversed_from_id=move.id, book_id=move.book_id,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
    )
    db.add(new_move)
    db.flush()

    # 借贷互换 + 摘要前缀
    for idx, src in enumerate(src_lines, start=1):
        line = AccountMoveLine(
            move_id=new_move.id, line_no=idx, book_id=move.book_id,
            summary=f"红冲：{src.summary}", account_id=src.account_id,
            partner_id=src.partner_id, department=src.department, project=src.project,
            debit=_dec(src.credit),     # 借→贷
            credit=_dec(src.debit),     # 贷→借
            create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
        )
        db.add(line)
    db.flush()

    # 红冲单直接过账（生成凭证号）
    new_move = post_move(db, new_move.id, user_id)

    # 原单标记已红冲并互链
    move.state = "voided"
    move.reversed_move_id = new_move.id
    move.write_uid = user_id
    move.write_date = now
    db.flush()
    return new_move


# ==================== 序列化 ====================

def line_to_dict(ln: AccountMoveLine, acc: AccountAccount | None = None) -> dict:
    return {
        "id": ln.id, "line_no": ln.line_no, "summary": ln.summary,
        "account_id": ln.account_id,
        "account_code": acc.code if acc else None,
        "account_name": acc.name if acc else None,
        "account_display": f"{acc.code} {acc.name}" if acc else None,
        "partner_id": ln.partner_id,
        "department": ln.department, "project": ln.project,
        "debit": str(_dec(ln.debit)), "credit": str(_dec(ln.credit)),
    }


def move_to_dict(db: Session, move: AccountMove, with_lines: bool = True) -> dict:
    journal = db.get(AccountJournal, move.journal_id)
    data = {
        "id": move.id, "name": move.name, "journal_id": move.journal_id,
        "journal_code": journal.code if journal else None,
        "journal_name": journal.name if journal else None,
        "move_date": move.move_date.isoformat() if move.move_date else None,
        "period": move.period, "state": move.state, "source_type": move.source_type,
        "attachment_count": move.attachment_count, "remark": move.remark,
        "reversed_move_id": move.reversed_move_id,
        "reversed_from_id": move.reversed_from_id,
        "is_template": move.is_template, "template_name": move.template_name,
        "book_id": move.book_id,
    }
    lines = lines_of(db, move.id) if with_lines else []
    items = []
    for ln in lines:
        acc = db.get(AccountAccount, ln.account_id) if ln.account_id else None
        items.append(line_to_dict(ln, acc))
    data["lines"] = items
    total_d = sum((Decimal(i["debit"]) for i in items), ZERO)
    total_c = sum((Decimal(i["credit"]) for i in items), ZERO)
    data["total_debit"] = str(total_d)
    data["total_credit"] = str(total_c)
    data["diff"] = str(total_d - total_c)
    return data
