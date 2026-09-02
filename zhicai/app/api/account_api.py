# -*- coding: utf-8 -*-
"""记账核心 API（M2）：凭证 CRUD / 过账 / 红冲 / 期间锁 / 结转 / 账簿 / 报表。

业务动作走显式端点（项目书 5.1 原则 3），业务逻辑一律在 service 层。
"""
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.book_context import ALL_BOOKS, get_book_id
from ..core.db import get_db
from ..core.errors import BizError
from ..modules.account import ledger_service, move_service, report_service
from ..modules.account.models import (
    AccountAccount,
    AccountJournal,
    AccountMove,
    AccountMoveLine,
    AccountPeriodClose,
)
from ..modules.base.models import ResUsers
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/acc", tags=["account"])


def _require_book(request: Request) -> int:
    """记账作业必须选定具体账套（总览模式不允许）。"""
    book_id = get_book_id(request)
    if book_id == ALL_BOOKS or not isinstance(book_id, int):
        raise BizError("book_required", "请先在右上角选择一个客户账套，再进行记账操作")
    return book_id


def _parse_date(v) -> date:
    if isinstance(v, date):
        return v
    if not v:
        raise BizError("date_required", "请选择凭证日期")
    return date.fromisoformat(str(v)[:10])


def _current_period() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


# ==================== 凭证 ====================

class LineBody(BaseModel):
    summary: str = ""
    account_id: int | None = None
    partner_id: int | None = None
    department: str | None = None
    project: str | None = None
    debit: str | float | int = "0"
    credit: str | float | int = "0"


class MoveBody(BaseModel):
    journal_id: int
    move_date: str
    lines: list[LineBody] = []
    attachment_count: int = 0
    remark: str | None = None
    template_name: str | None = None


@router.get("/moves")
def list_moves(
    request: Request,
    period: str | None = Query(None, description="期间 YYYY-MM"),
    period_from: str | None = Query(None),
    period_to: str | None = Query(None),
    journal_id: int | None = Query(None),
    state: str | None = Query(None),
    source_type: str | None = Query(None),
    kw: str | None = Query(None, description="摘要/凭证号关键词"),
    account_id: int | None = Query(None, description="按科目过滤（含该科目的凭证）"),
    limit: int = Query(80, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: ResUsers = Depends(require_role("read")),
    db: Session = Depends(get_db),
):
    """凭证列表：默认按期间倒序，支持多条件筛选（项目书 7.5）。"""
    book_id = _require_book(request)

    q = select(AccountMove).where(
        AccountMove.book_id == book_id,
        AccountMove.active.is_(True),
        AccountMove.is_template.is_(False),
    )
    if period:
        q = q.where(AccountMove.period == period)
    if period_from:
        q = q.where(AccountMove.period >= period_from)
    if period_to:
        q = q.where(AccountMove.period <= period_to)
    if journal_id:
        q = q.where(AccountMove.journal_id == journal_id)
    if state:
        q = q.where(AccountMove.state == state)
    if source_type:
        q = q.where(AccountMove.source_type == source_type)
    if kw:
        like = f"%{kw.strip()}%"
        # 摘要命中走分录表，凭证号命中走主表
        sub = select(AccountMoveLine.move_id).where(
            AccountMoveLine.active.is_(True), AccountMoveLine.summary.ilike(like))
        q = q.where(or_(AccountMove.name.ilike(like), AccountMove.id.in_(sub)))
    if account_id:
        sub2 = select(AccountMoveLine.move_id).where(
            AccountMoveLine.active.is_(True), AccountMoveLine.account_id == account_id)
        q = q.where(AccountMove.id.in_(sub2))

    # 注意：必须用 func.count() + select_from(subquery)。
    # 若写 select(AccountMove.id).select_from(subquery)，SQLAlchemy 会把 account_move 也加进
    # FROM，与子查询形成笛卡尔积，导致 total 被放大 N 倍。
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(
        q.order_by(AccountMove.period.desc(), AccountMove.move_date.desc(),
                   AccountMove.id.desc()).limit(limit).offset(offset)
    ).scalars().all()

    return {
        "total": total,
        "moves": [move_service.move_to_dict(db, m, with_lines=False) for m in rows],
    }


@router.get("/moves/{move_id}")
def get_move_detail(move_id: int, user: ResUsers = Depends(require_role("read")),
                    db: Session = Depends(get_db)):
    move = move_service.get_move(db, move_id)
    data = move_service.move_to_dict(db, move, with_lines=True)
    if move.journal_id:
        j = db.get(AccountJournal, move.journal_id)
        data["journals"] = [{"id": j.id, "code": j.code, "name": j.name}] if j else []
    return {"move": data}


@router.post("/moves")
def create_move(body: MoveBody, request: Request,
                user: ResUsers = Depends(require_role("create")),
                db: Session = Depends(get_db)):
    book_id = _require_book(request)
    move = move_service.create_move(
        db, book_id=book_id, journal_id=body.journal_id,
        move_date=_parse_date(body.move_date),
        lines=[l.model_dump() for l in body.lines],
        attachment_count=body.attachment_count, remark=body.remark,
        source_type="manual", user_id=user.id,
    )
    return {"ok": True, "move": move_service.move_to_dict(db, move)}


@router.put("/moves/{move_id}")
def update_move(move_id: int, body: MoveBody, request: Request,
                user: ResUsers = Depends(require_role("write")),
                db: Session = Depends(get_db)):
    _require_book(request)
    move = move_service.update_move(
        db, move_id, user_id=user.id,
        journal_id=body.journal_id, move_date=_parse_date(body.move_date),
        lines=[l.model_dump() for l in body.lines],
        attachment_count=body.attachment_count, remark=body.remark,
    )
    return {"ok": True, "move": move_service.move_to_dict(db, move)}


@router.delete("/moves/{move_id}")
def delete_move(move_id: int, user: ResUsers = Depends(require_role("delete")),
                db: Session = Depends(get_db)):
    move_service.delete_move(db, move_id, user.id)
    return {"ok": True}


@router.post("/moves/{move_id}/post")
def post_move(move_id: int, user: ResUsers = Depends(require_role("write")),
              db: Session = Depends(get_db)):
    """过账：跑 6.5 全部约束校验后生成凭证号。"""
    move = move_service.post_move(db, move_id, user.id)
    return {"ok": True, "move": move_service.move_to_dict(db, move)}


class BulkBody(BaseModel):
    ids: list[int]


@router.post("/moves/bulk-post")
def bulk_post(body: BulkBody, user: ResUsers = Depends(require_role("write")),
              db: Session = Depends(get_db)):
    """批量过账：逐单执行，失败原因逐单返回。"""
    return {"ok": True, **move_service.post_moves_bulk(db, body.ids, user.id)}


class ReverseBody(BaseModel):
    reverse_date: str | None = None


@router.post("/moves/{move_id}/reverse")
def reverse_move(move_id: int, body: ReverseBody | None = None,
                 user: ResUsers = Depends(require_role("write")),
                 db: Session = Depends(get_db)):
    """红冲：生成反向凭证并互链，原凭证置为 voided。"""
    rdate = _parse_date(body.reverse_date) if (body and body.reverse_date) else None
    new_move = move_service.reverse_move(db, move_id, user.id, reverse_date=rdate)
    return {"ok": True, "move": move_service.move_to_dict(db, new_move)}


# ==================== 期间结账 ====================

class PeriodBody(BaseModel):
    period: str
    note: str | None = None


@router.get("/periods")
def list_periods(request: Request, user: ResUsers = Depends(require_role("read")),
                 db: Session = Depends(get_db)):
    """期间列表：取账套内所有已结账期间 + 当前期间。"""
    book_id = _require_book(request)
    rows = db.execute(
        select(AccountPeriodClose).where(AccountPeriodClose.book_id == book_id,
                                         AccountPeriodClose.active.is_(True))
        .order_by(AccountPeriodClose.period.desc())
    ).scalars().all()
    closed = {r.period for r in rows if r.closed}
    # 有凭证的期间也列出来
    periods = sorted({
        p for (p,) in db.execute(
            select(AccountMove.period).where(AccountMove.book_id == book_id,
                                             AccountMove.active.is_(True)).distinct())
    }, reverse=True)
    for p in periods:
        if p not in closed:
            closed.add(p)
    cur = _current_period()
    if cur not in periods:
        periods.insert(0, cur)
    return {"periods": [
        {"period": p, "closed": p in {r.period for r in rows if r.closed},
         "closed_at": next((r.closed_at.isoformat(sep=" ") for r in rows
                            if r.period == p and r.closed_at), None)}
        for p in periods
    ]}


@router.post("/period/close")
def close_period(body: PeriodBody, request: Request,
                 user: ResUsers = Depends(require_role("write")),
                 db: Session = Depends(get_db)):
    book_id = _require_book(request)
    row = ledger_service  # noqa（保持 import 明确）
    from ..modules.account.move_service import close_period as _close
    _close(db, book_id, body.period, user.id, body.note)
    return {"ok": True, "period": body.period, "closed": True}


@router.post("/period/open")
def open_period(body: PeriodBody, request: Request,
                user: ResUsers = Depends(require_role("write")),
                db: Session = Depends(get_db)):
    book_id = _require_book(request)
    from ..modules.account.move_service import open_period as _open
    _open(db, book_id, body.period, user.id)
    return {"ok": True, "period": body.period, "closed": False}


# ==================== 期末结转 ====================

@router.post("/carry-forward")
def carry_forward(body: PeriodBody, request: Request,
                  user: ResUsers = Depends(require_role("write")),
                  db: Session = Depends(get_db)):
    """一键结转损益 → 本年利润（3103），同期间重复执行会报错。"""
    book_id = _require_book(request)
    move = ledger_service.carry_forward(db, book_id, body.period, user.id)
    return {"ok": True, "move": move_service.move_to_dict(db, move)}


# ==================== 账簿查询 ====================

@router.get("/ledger/general")
def general_ledger(request: Request, period_from: str, period_to: str,
                   account_code: str | None = None,
                   user: ResUsers = Depends(require_role("read")),
                   db: Session = Depends(get_db)):
    """总账：科目 × 期间区间（期初/本期借/本期贷/期末）。"""
    book_id = _require_book(request)
    rows = ledger_service.general_ledger(db, book_id, period_from, period_to, account_code)
    return {"rows": rows, "period_from": period_from, "period_to": period_to}


@router.get("/ledger/subsidiary")
def subsidiary_ledger(request: Request, account_id: int, period_from: str, period_to: str,
                      user: ResUsers = Depends(require_role("read")),
                      db: Session = Depends(get_db)):
    """明细账：科目下按凭证逐笔展开。"""
    book_id = _require_book(request)
    return ledger_service.subsidiary_ledger(db, book_id, account_id, period_from, period_to)


@router.get("/ledger/trial")
def trial_balance(request: Request, period_from: str, period_to: str,
                  only_nonzero: bool = True,
                  user: ResUsers = Depends(require_role("read")),
                  db: Session = Depends(get_db)):
    """科目余额表：全科目期初/发生/期末。

    注意：列表含非末级科目（便于查看科目层级，父科目余额 = 其下末级科目之和），
    但**合计只累加末级科目**，否则父子同时计入会把金额算两遍，导致借贷合计不平。
    """
    from decimal import Decimal
    book_id = _require_book(request)
    rows = ledger_service.trial_balance(db, book_id, period_from, period_to, only_nonzero)
    leafs = [r for r in rows if r["is_leaf"]]
    totals = {
        "debit_balance": str(sum((Decimal(r["debit_balance"]) for r in leafs), Decimal("0"))),
        "credit_balance": str(sum((Decimal(r["credit_balance"]) for r in leafs), Decimal("0"))),
        "debit": str(sum((Decimal(r["debit"]) for r in leafs), Decimal("0"))),
        "credit": str(sum((Decimal(r["credit"]) for r in leafs), Decimal("0"))),
    }
    return {"rows": rows, "totals": totals,
            "period_from": period_from, "period_to": period_to}


# ==================== 财务报表 ====================

@router.get("/report/balance-sheet")
def balance_sheet(request: Request, period: str | None = None,
                  user: ResUsers = Depends(require_role("read")),
                  db: Session = Depends(get_db)):
    """资产负债表（含资产=负债+权益平衡校验，DoD ③）。"""
    book_id = _require_book(request)
    return report_service.balance_sheet(db, book_id, period or _current_period())


@router.get("/report/income")
def income_statement(request: Request, period_from: str, period_to: str,
                     user: ResUsers = Depends(require_role("read")),
                     db: Session = Depends(get_db)):
    """利润表（DoD ④：净利润 = 本年利润科目发生额）。"""
    book_id = _require_book(request)
    return report_service.income_statement(db, book_id, period_from, period_to)


# ==================== 辅助数据 ====================

@router.get("/accounts/leaf")
def leaf_accounts(request: Request, kw: str | None = None,
                  user: ResUsers = Depends(require_login),
                  db: Session = Depends(get_db)):
    """末级科目列表（凭证录入的科目联想数据源，仅末级可记账）。"""
    book_id = _require_book(request)
    q = select(AccountAccount).where(
        AccountAccount.book_id == book_id,
        AccountAccount.active.is_(True),
        AccountAccount.is_leaf.is_(True),
    )
    if kw:
        like = f"%{kw.strip()}%"
        q = q.where(or_(AccountAccount.code.ilike(like), AccountAccount.name.ilike(like)))
    rows = db.execute(q.order_by(AccountAccount.code).limit(200)).scalars().all()
    return {"accounts": [
        {"id": a.id, "code": a.code, "name": a.name, "display": f"{a.code} {a.name}",
         "direction": a.direction, "aux_partner": "partner" in (a.auxiliary_flags or "")}
        for a in rows
    ]}


@router.get("/journals")
def list_journals(request: Request, user: ResUsers = Depends(require_login),
                  db: Session = Depends(get_db)):
    book_id = _require_book(request)
    rows = db.execute(
        select(AccountJournal).where(AccountJournal.book_id == book_id,
                                     AccountJournal.active.is_(True)).order_by(AccountJournal.id)
    ).scalars().all()
    return {"journals": [{"id": j.id, "code": j.code, "name": j.name,
                          "journal_type": j.journal_type} for j in rows]}


# ==================== 常用凭证模板 ====================

@router.get("/templates")
def list_templates(request: Request, user: ResUsers = Depends(require_login),
                   db: Session = Depends(get_db)):
    book_id = _require_book(request)
    rows = db.execute(
        select(AccountMove).where(AccountMove.book_id == book_id,
                                  AccountMove.active.is_(True),
                                  AccountMove.is_template.is_(True))
        .order_by(AccountMove.id.desc())
    ).scalars().all()
    return {"templates": [move_service.move_to_dict(db, m) for m in rows]}


class TemplateBody(BaseModel):
    template_name: str
    journal_id: int
    move_date: str
    lines: list[LineBody] = []


@router.post("/templates")
def save_template(body: TemplateBody, request: Request,
                  user: ResUsers = Depends(require_role("create")),
                  db: Session = Depends(get_db)):
    """把当前凭证存为常用模板（含科目不含金额，项目书 7.5）。"""
    book_id = _require_book(request)
    lines = [{"summary": l.summary, "account_id": l.account_id, "partner_id": l.partner_id,
              "department": l.department, "project": l.project,
              "debit": "0", "credit": "0"}   # 模板不带金额
             for l in body.lines]
    move = move_service.create_move(
        db, book_id=book_id, journal_id=body.journal_id,
        move_date=_parse_date(body.move_date), lines=lines,
        user_id=user.id, is_template=True, template_name=body.template_name)
    return {"ok": True, "template": move_service.move_to_dict(db, move)}
