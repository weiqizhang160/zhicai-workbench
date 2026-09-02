# -*- coding: utf-8 -*-
"""税务申报 API（M4，项目书 7.9）：台账 / 批量生成 / 计算底稿 / 状态流转 / 官网链接。

注意：本系统**不做自动申报**，只做登记、计算与官网导航（政策安全原因）。
"""
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.book_context import get_book_id
from ..core.db import get_db
from ..core.errors import BizError
from ..modules.base.models import IrConfig, ResUsers
from ..modules.res_partner.models import ResBook
from ..modules.tax_decl import calc_service, calendar_service
from ..modules.tax_decl.models import TaxDeclItem
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/tax", tags=["tax_decl"])

# 官网直达链接（存 ir_config，用户可在「参数配置」维护）
SITE_LINKS_KEY = "tax.official_links"
DEFAULT_SITE_LINKS = {
    "vat": {"name": "电子税务局（增值税申报）",
            "url": "https://etax.chinatax.gov.cn/"},
    "surtax": {"name": "电子税务局（附加税申报）",
               "url": "https://etax.chinatax.gov.cn/"},
    "cit_quarterly": {"name": "电子税务局（企业所得税预缴）",
                      "url": "https://etax.chinatax.gov.cn/"},
    "cit_annual": {"name": "电子税务局（企业所得税汇算）",
                   "url": "https://etax.chinatax.gov.cn/"},
    "iit": {"name": "自然人电子税务局（个税）",
            "url": "https://etax.chinatax.gov.cn/"},
    "stamp": {"name": "电子税务局（印花税申报）",
              "url": "https://etax.chinatax.gov.cn/"},
}


def _ensure_links(db: Session) -> None:
    row = db.execute(select(IrConfig).where(IrConfig.key == SITE_LINKS_KEY)).scalar_one_or_none()
    if row is None:
        db.add(IrConfig(key=SITE_LINKS_KEY,
                        value=json.dumps(DEFAULT_SITE_LINKS, ensure_ascii=False)))
        db.flush()


# ==================== 台账查询 ====================

def _item_to_dict(db: Session, it: TaxDeclItem, with_book: bool = True) -> dict:
    book = db.get(ResBook, it.book_id) if with_book else None
    return {
        "id": it.id, "book_id": it.book_id,
        "book_name": book.short_name if book else None,
        "book_code": book.code if book else None,
        "tax_kind": it.tax_kind, "period": it.period,
        "due_date": it.due_date.isoformat() if it.due_date else None,
        "state": it.state,
        "overdue": it.is_overdue,
        "computed_amount": str(it.computed_amount or 0),
        "declared_amount": (str(it.declared_amount) if it.declared_amount is not None else None),
        "paid_date": it.paid_date.isoformat() if it.paid_date else None,
        "calc_snapshot": it.calc_snapshot,
        "remark": it.remark, "source": it.source, "rule_id": it.rule_id,
    }


@router.get("/items")
def list_items(
    period: str | None = Query(None, description="属期 YYYY-MM / YYYYQn / YYYY"),
    due_month: str | None = Query(None, description="按截止日所在月过滤 YYYY-MM"),
    tax_kind: str | None = Query(None),
    state: str | None = Query(None),
    book_id: int | None = Query(None),
    overdue_only: bool = Query(False),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    user: ResUsers = Depends(require_login),
    db: Session = Depends(get_db),
):
    """申报台账列表（总览模式：默认跨全部账套）。"""
    q = select(TaxDeclItem).where(TaxDeclItem.active.is_(True))
    if period:
        q = q.where(TaxDeclItem.period == period)
    if due_month:
        q = q.where(TaxDeclItem.due_date >= date(int(due_month[:4]), int(due_month[5:7]), 1),
                    TaxDeclItem.due_date <= _month_end(due_month))
    if tax_kind:
        q = q.where(TaxDeclItem.tax_kind == tax_kind)
    if state:
        q = q.where(TaxDeclItem.state == state)
    if book_id:
        q = q.where(TaxDeclItem.book_id == book_id)
    if overdue_only:
        today = date.today()
        q = q.where(TaxDeclItem.due_date < today,
                    TaxDeclItem.state.in_(["pending", "preparing"]))

    rows = db.execute(
        q.order_by(TaxDeclItem.due_date, TaxDeclItem.book_id, TaxDeclItem.id)
        .limit(limit).offset(offset)).scalars().all()
    return {"items": [_item_to_dict(db, r) for r in rows], "total": len(rows)}


def _month_end(period: str) -> date:
    from datetime import timedelta
    y, m = int(period[:4]), int(period[5:7])
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - timedelta(days=1)


# ==================== 批量生成（幂等） ====================

class GenerateBody(BaseModel):
    periods: list[str]
    book_ids: list[int] | None = None


@router.post("/generate")
def generate(body: GenerateBody, user: ResUsers = Depends(require_role("create")),
             db: Session = Depends(get_db)):
    """按征期规则批量生成申报台账（已存在自动跳过，可重复执行）。"""
    calc_service.ensure_policy_config(db)
    return {"ok": True, **calendar_service.generate_items(
        db, body.periods, body.book_ids, user.id)}


# ==================== 计算底稿 ====================

class ComputeBody(BaseModel):
    overrides: dict | None = None


@router.post("/items/{item_id}/compute")
def compute_item(item_id: int, body: ComputeBody | None = None,
                 user: ResUsers = Depends(require_role("write")),
                 db: Session = Depends(get_db)):
    """计算应纳税额并生成计算底稿快照（可追溯取数来源）。"""
    it = db.get(TaxDeclItem, item_id)
    if it is None or not it.active:
        raise BizError("not_found", "台账行不存在")
    snap = calc_service.compute(db, it, body.overrides if body else None)
    return {"ok": True, "snapshot": snap, "item": _item_to_dict(db, it)}


@router.get("/items/{item_id}/snapshot")
def get_snapshot(item_id: int, user: ResUsers = Depends(require_login),
                 db: Session = Depends(get_db)):
    it = db.get(TaxDeclItem, item_id)
    if it is None or not it.active:
        raise BizError("not_found", "台账行不存在")
    snap = None
    if it.calc_snapshot:
        try:
            snap = json.loads(it.calc_snapshot)
        except (ValueError, TypeError):
            snap = None
    return {"snapshot": snap, "item": _item_to_dict(db, it)}


# ==================== 状态流转 ====================

class DeclareBody(BaseModel):
    declared_amount: str
    remark: str | None = None


@router.post("/items/{item_id}/submit")
def mark_submitted(item_id: int, body: DeclareBody,
                   user: ResUsers = Depends(require_role("write")),
                   db: Session = Depends(get_db)):
    """标记已申报（填实缴额）。"""
    it = db.get(TaxDeclItem, item_id)
    if it is None or not it.active:
        raise BizError("not_found", "台账行不存在")
    from decimal import Decimal
    it.declared_amount = Decimal(str(body.declared_amount or 0))
    it.state = "submitted"
    if body.remark:
        it.remark = body.remark
    it.write_uid = user.id
    it.write_date = datetime.now()
    db.flush()
    return {"ok": True, "item": _item_to_dict(db, it)}


class PaidBody(BaseModel):
    paid_date: str | None = None
    remark: str | None = None


@router.post("/items/{item_id}/pay")
def mark_paid(item_id: int, body: PaidBody | None = None,
              user: ResUsers = Depends(require_role("write")),
              db: Session = Depends(get_db)):
    """标记已缴款（填缴款日期）→ 状态 paid。"""
    it = db.get(TaxDeclItem, item_id)
    if it is None or not it.active:
        raise BizError("not_found", "台账行不存在")
    it.paid_date = date.fromisoformat(body.paid_date[:10]) if (body and body.paid_date) \
        else date.today()
    if it.declared_amount is None:
        it.declared_amount = it.computed_amount
    it.state = "paid"
    if body and body.remark:
        it.remark = body.remark
    it.write_uid = user.id
    it.write_date = datetime.now()
    db.flush()
    return {"ok": True, "item": _item_to_dict(db, it)}


class ExemptBody(BaseModel):
    reason: str = ""
    zero: bool = False


@router.post("/items/{item_id}/exempt")
def mark_exempt(item_id: int, body: ExemptBody | None = None,
                user: ResUsers = Depends(require_role("write")),
                db: Session = Depends(get_db)):
    """标记免税 / 零申报（记录原因）。"""
    it = db.get(TaxDeclItem, item_id)
    if it is None or not it.active:
        raise BizError("not_found", "台账行不存在")
    reason = (body.reason if body else "") or ""
    it.state = "exempt"
    it.declared_amount = 0
    it.remark = (f"零申报：{reason}" if (body and body.zero) else f"免税：{reason}").strip("：")
    it.write_uid = user.id
    it.write_date = datetime.now()
    db.flush()
    return {"ok": True, "item": _item_to_dict(db, it)}


class StateBody(BaseModel):
    state: str


@router.post("/items/{item_id}/state")
def set_state(item_id: int, body: StateBody,
              user: ResUsers = Depends(require_role("write")),
              db: Session = Depends(get_db)):
    """直接设置状态（回退/流转用）。"""
    allowed = {"pending", "preparing", "submitted", "paid", "done", "exempt"}
    if body.state not in allowed:
        raise BizError("state_invalid", f"状态必须是 {sorted(allowed)} 之一")
    it = db.get(TaxDeclItem, item_id)
    if it is None or not it.active:
        raise BizError("not_found", "台账行不存在")
    it.state = body.state
    it.write_uid = user.id
    it.write_date = datetime.now()
    db.flush()
    return {"ok": True, "item": _item_to_dict(db, it)}


# ==================== 申报日历 ====================

@router.get("/calendar")
def calendar(month: str = Query(..., description="YYYY-MM，按截止日所在月聚合"),
             user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    """申报日历数据源：按截止日所在月聚合，返回每日的申报项与状态统计。"""
    start = date(int(month[:4]), int(month[5:7]), 1)
    end = _month_end(month)
    rows = db.execute(
        select(TaxDeclItem).where(
            TaxDeclItem.active.is_(True),
            TaxDeclItem.due_date >= start, TaxDeclItem.due_date <= end)
        .order_by(TaxDeclItem.due_date, TaxDeclItem.book_id)).scalars().all()

    by_day: dict[str, list] = {}
    for r in rows:
        key = r.due_date.isoformat() if r.due_date else "未设置"
        by_day.setdefault(key, []).append(_item_to_dict(db, r))

    stats = {"total": len(rows), "overdue": 0, "pending": 0, "submitted": 0,
             "paid": 0, "exempt": 0, "done": 0, "preparing": 0}
    for r in rows:
        if r.is_overdue:
            stats["overdue"] += 1
        stats[r.state] = stats.get(r.state, 0) + 1

    return {"month": month, "days": by_day, "stats": stats}


# ==================== 官网链接中心 ====================

@router.get("/links")
def official_links(user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    """各税种的电子税务局直达链接（存在 ir_config，用户可维护）。

    系统只做导航与登记，不做自动申报。
    """
    _ensure_links(db)
    row = db.execute(select(IrConfig).where(IrConfig.key == SITE_LINKS_KEY)).scalar_one_or_none()
    try:
        links = json.loads(row.value) if row and row.value else {}
    except (ValueError, TypeError):
        links = {}
    return {"links": links or DEFAULT_SITE_LINKS}
