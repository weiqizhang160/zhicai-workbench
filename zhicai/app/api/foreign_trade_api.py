# -*- coding: utf-8 -*-
"""外贸专区 API（M6，项目书 7.10）：报关单 / 收汇 / 出口退税 / 平台链接 / 汇总。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.book_context import ALL_BOOKS, get_book_id
from ..core.db import get_db
from ..core.errors import BizError
from ..modules.base.models import ResUsers
from ..modules.foreign_trade import service as ft_service
from ..modules.foreign_trade.models import FtCustomsDecl, FtExportRefund, FxFxReceipt
from ..modules.res_partner.models import ResBook
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/ft", tags=["foreign_trade"])


def _require_ft_book(db: Session, book_id: int) -> ResBook:
    """外贸数据只允许落在外贸账套（防止误挂）。"""
    book = db.get(ResBook, book_id)
    if book is None or not book.active:
        raise BizError("not_found", "客户账套不存在")
    if not book.is_foreign_trade:
        raise BizError("not_foreign_trade",
                       f"客户 {book.short_name} 不是外贸客户，请在客户档案勾选外贸标记")
    return book


def _resolve_book(db: Session, request: Request, explicit: int | None = None) -> int:
    if explicit is not None:
        _require_ft_book(db, explicit)
        return explicit
    bid = get_book_id(request)
    if bid == ALL_BOOKS:
        raise BizError("book_required", "外贸数据需在指定客户账套下操作（请先切换账套）")
    _require_ft_book(db, bid)
    return bid


# ==================== 报关单 ====================

@router.get("/decls")
def list_decls(book_id: int | None = Query(None),
               keyword: str | None = Query(None),
               limit: int = Query(500, ge=1, le=2000),
               user: ResUsers = Depends(require_login),
               db: Session = Depends(get_db)):
    """报关单列表（只显示外贸账套的报关单）。"""
    ft_books = db.execute(
        select(ResBook.id).where(ResBook.active.is_(True), ResBook.is_foreign_trade.is_(True))
    ).scalars().all()
    q = select(FtCustomsDecl).where(
        FtCustomsDecl.active.is_(True), FtCustomsDecl.book_id.in_(ft_books or [0]))
    if book_id:
        q = q.where(FtCustomsDecl.book_id == book_id)
    if keyword:
        kw = f"%{keyword.strip()}%"
        q = q.where(FtCustomsDecl.decl_no.like(kw) | FtCustomsDecl.customer_abroad.like(kw))
    rows = db.execute(q.order_by(FtCustomsDecl.export_date.desc(), FtCustomsDecl.id.desc())
                      .limit(limit)).scalars().all()
    return {"items": [ft_service.decl_to_dict(db, d, with_lines=False) for d in rows]}


@router.get("/decls/{decl_id}")
def get_decl(decl_id: int, user: ResUsers = Depends(require_login),
             db: Session = Depends(get_db)):
    d = db.get(FtCustomsDecl, decl_id)
    if d is None or not d.active:
        raise BizError("not_found", "报关单不存在")
    receipts = db.execute(
        select(FxFxReceipt).where(
            FxFxReceipt.decl_id == decl_id, FxFxReceipt.active.is_(True))
        .order_by(FxFxReceipt.receipt_date)
    ).scalars().all()
    refunds = db.execute(
        select(FtExportRefund).where(
            FtExportRefund.decl_id == decl_id, FtExportRefund.active.is_(True))
    ).scalars().all()
    return {
        "decl": ft_service.decl_to_dict(db, d, with_lines=True),
        "receipts": [ft_service.receipt_to_dict(db, r) for r in receipts],
        "refunds": [ft_service.refund_to_dict(db, r) for r in refunds],
    }


class DeclLineBody(BaseModel):
    hs_code: str | None = None
    goods_name: str
    qty: str | float | None = None
    unit: str | None = None
    unit_price: str | float | None = None
    amount: str | float | None = None
    remark: str | None = None


class DeclBody(BaseModel):
    book_id: int | None = None
    decl_no: str
    export_date: str
    trade_mode: str = "FOB"
    currency: str = "USD"
    fx_rate: str | float = "1"
    usd_amount: str | float = "0"
    customer_abroad: str | None = None
    goods_count: int = 0
    remark: str | None = None
    lines: list[DeclLineBody] | None = None


@router.post("/decls")
def create_decl(body: DeclBody, request: Request,
                user: ResUsers = Depends(require_role("create")),
                db: Session = Depends(get_db)):
    book_id = _resolve_book(db, request, body.book_id)
    decl = ft_service.create_decl(
        db, book_id=book_id, decl_no=body.decl_no,
        export_date=date.fromisoformat(body.export_date[:10]),
        trade_mode=body.trade_mode, currency=body.currency, fx_rate=str(body.fx_rate),
        usd_amount=str(body.usd_amount), customer_abroad=body.customer_abroad,
        goods_count=body.goods_count, remark=body.remark,
        lines=[ln.model_dump() for ln in body.lines] if body.lines else None,
        user_id=user.id,
    )
    return {"ok": True, "decl": ft_service.decl_to_dict(db, decl, with_lines=True)}


class ImportBody(BaseModel):
    book_id: int | None = None
    rows: list[list[str]]


@router.post("/decls/import-commit")
def import_decls(body: ImportBody, request: Request,
                 user: ResUsers = Depends(require_role("create")),
                 db: Session = Depends(get_db)):
    """单一窗口 CSV 导入（rows：二维数组，首行表头）。"""
    book_id = _resolve_book(db, request, body.book_id)
    result = ft_service.import_decl_rows(db, book_id, body.rows, user.id)
    return {"ok": True, **result}


@router.delete("/decls/{decl_id}")
def delete_decl(decl_id: int, user: ResUsers = Depends(require_role("delete")),
                db: Session = Depends(get_db)):
    d = db.get(FtCustomsDecl, decl_id)
    if d is None or not d.active:
        raise BizError("not_found", "报关单不存在")
    now = datetime.now()
    d.active = False
    d.write_uid = user.id
    d.write_date = now
    # 子行一并软删
    for ln in ft_service.lines_of(db, decl_id):
        ln.active = False
        ln.write_uid = user.id
        ln.write_date = now
    db.flush()
    return {"ok": True}


# ==================== 收汇 ====================

@router.get("/fx-receipts")
def list_receipts(book_id: int | None = Query(None),
                  decl_id: int | None = Query(None),
                  kind: str | None = Query(None),
                  limit: int = Query(500, ge=1, le=2000),
                  user: ResUsers = Depends(require_login),
                  db: Session = Depends(get_db)):
    ft_books = db.execute(
        select(ResBook.id).where(ResBook.active.is_(True), ResBook.is_foreign_trade.is_(True))
    ).scalars().all()
    q = select(FxFxReceipt).where(
        FxFxReceipt.active.is_(True), FxFxReceipt.book_id.in_(ft_books or [0]))
    if book_id:
        q = q.where(FxFxReceipt.book_id == book_id)
    if decl_id:
        q = q.where(FxFxReceipt.decl_id == decl_id)
    if kind:
        q = q.where(FxFxReceipt.kind == kind)
    rows = db.execute(q.order_by(FxFxReceipt.receipt_date.desc(), FxFxReceipt.id.desc())
                      .limit(limit)).scalars().all()
    return {"items": [ft_service.receipt_to_dict(db, r) for r in rows]}


class ReceiptBody(BaseModel):
    book_id: int | None = None
    decl_id: int | None = None
    receipt_date: str
    currency: str = "USD"
    amount: str | float
    fx_rate: str | float = "1"
    kind: str = "receipt"
    bank_fee: str | float = "0"
    remark: str | None = None


@router.post("/fx-receipts")
def create_receipt(body: ReceiptBody, request: Request,
                   user: ResUsers = Depends(require_role("create")),
                   db: Session = Depends(get_db)):
    book_id = _resolve_book(db, request, body.book_id)
    row = ft_service.create_receipt(
        db, book_id=book_id, decl_id=body.decl_id,
        receipt_date=date.fromisoformat(body.receipt_date[:10]),
        currency=body.currency, amount=str(body.amount), fx_rate=str(body.fx_rate),
        kind=body.kind, bank_fee=str(body.bank_fee), remark=body.remark, user_id=user.id,
    )
    return {"ok": True, "receipt": ft_service.receipt_to_dict(db, row)}


@router.delete("/fx-receipts/{receipt_id}")
def delete_receipt(receipt_id: int, user: ResUsers = Depends(require_role("delete")),
                   db: Session = Depends(get_db)):
    r = db.get(FxFxReceipt, receipt_id)
    if r is None or not r.active:
        raise BizError("not_found", "收汇记录不存在")
    r.active = False
    r.write_uid = user.id
    r.write_date = datetime.now()
    db.flush()
    return {"ok": True}


# ==================== 出口退税 ====================

@router.get("/refunds")
def list_refunds(book_id: int | None = Query(None),
                 status: str | None = Query(None),
                 limit: int = Query(500, ge=1, le=2000),
                 user: ResUsers = Depends(require_login),
                 db: Session = Depends(get_db)):
    ft_books = db.execute(
        select(ResBook.id).where(ResBook.active.is_(True), ResBook.is_foreign_trade.is_(True))
    ).scalars().all()
    q = select(FtExportRefund).where(
        FtExportRefund.active.is_(True), FtExportRefund.book_id.in_(ft_books or [0]))
    if book_id:
        q = q.where(FtExportRefund.book_id == book_id)
    if status:
        q = q.where(FtExportRefund.status == status)
    rows = db.execute(q.order_by(FtExportRefund.period.desc(), FtExportRefund.id.desc())
                      .limit(limit)).scalars().all()
    return {"items": [ft_service.refund_to_dict(db, r) for r in rows]}


class RefundBody(BaseModel):
    book_id: int | None = None
    decl_id: int
    period: str
    kind: str = "免抵退"
    status: str = "collecting"
    refund_amount: str | float = "0"
    received_date: str | None = None
    remark: str | None = None


@router.post("/refunds")
def create_refund(body: RefundBody, request: Request,
                  user: ResUsers = Depends(require_role("create")),
                  db: Session = Depends(get_db)):
    book_id = _resolve_book(db, request, body.book_id)
    row = ft_service.create_refund(
        db, book_id=book_id, decl_id=body.decl_id, period=body.period, kind=body.kind,
        status=body.status, refund_amount=str(body.refund_amount),
        received_date=date.fromisoformat(body.received_date[:10]) if body.received_date else None,
        remark=body.remark, user_id=user.id,
    )
    return {"ok": True, "refund": ft_service.refund_to_dict(db, row)}


class RefundStatusBody(BaseModel):
    status: str
    received_date: str | None = None


@router.post("/refunds/{refund_id}/status")
def set_refund_status(refund_id: int, body: RefundStatusBody,
                      user: ResUsers = Depends(require_role("write")),
                      db: Session = Depends(get_db)):
    row = ft_service.set_refund_status(
        db, refund_id, body.status,
        date.fromisoformat(body.received_date[:10]) if body.received_date else None)
    row.write_uid = user.id
    row.write_date = datetime.now()
    db.flush()
    return {"ok": True, "refund": ft_service.refund_to_dict(db, row)}


# ==================== 平台链接 / 汇总 ====================

@router.get("/platform")
def get_platform(user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    return ft_service.get_platform(db)


class NotesBody(BaseModel):
    notes: str


@router.put("/platform/notes")
def save_notes(body: NotesBody, user: ResUsers = Depends(require_role("write")),
               db: Session = Depends(get_db)):
    ft_service.save_platform_notes(db, body.notes)
    return {"ok": True}


@router.get("/summary")
def ft_summary(user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    return ft_service.ft_summary(db)
