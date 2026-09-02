# -*- coding: utf-8 -*-
"""工资社保 API（M6，项目书 7.11）：批次 / 员工行 / 个税 / 确认生成凭证。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.book_context import ALL_BOOKS, get_book_id
from ..core.db import get_db
from ..core.errors import BizError
from ..modules.base.models import ResUsers
from ..modules.payroll import service as payroll_service
from ..modules.payroll.iit import compute_iit_monthly
from ..modules.payroll.models import PayrollBatch
from ..modules.res_partner.models import ResBook
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/payroll", tags=["payroll"])


def _resolve_book(db: Session, request: Request, explicit: int | None = None) -> int:
    """工资批次必须挂具体账套（总览模式需显式 book_id）。"""
    if explicit is not None:
        book = db.get(ResBook, explicit)
        if book is None or not book.active:
            raise BizError("not_found", "客户账套不存在")
        return explicit
    bid = get_book_id(request)
    if bid == ALL_BOOKS:
        raise BizError("book_required", "请先切换到具体客户账套，或显式指定 book_id")
    return bid


@router.get("/batches")
def list_batches(book_id: int | None = Query(None),
                 state: str | None = Query(None),
                 limit: int = Query(200, ge=1, le=1000),
                 user: ResUsers = Depends(require_login),
                 db: Session = Depends(get_db)):
    """工资批次列表（总览模式跨账套）。"""
    q = select(PayrollBatch).where(PayrollBatch.active.is_(True))
    if book_id:
        q = q.where(PayrollBatch.book_id == book_id)
    if state:
        q = q.where(PayrollBatch.state == state)
    rows = db.execute(q.order_by(PayrollBatch.period.desc(), PayrollBatch.id.desc())
                      .limit(limit)).scalars().all()
    return {"items": [payroll_service.batch_to_dict(db, b) for b in rows]}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, user: ResUsers = Depends(require_login),
              db: Session = Depends(get_db)):
    b = db.get(PayrollBatch, batch_id)
    if b is None or not b.active:
        raise BizError("not_found", "工资批次不存在")
    return {"batch": payroll_service.batch_to_dict(db, b, with_lines=True)}


class BatchBody(BaseModel):
    book_id: int | None = None
    period: str
    remark: str | None = None
    copy_from_last: bool = False


@router.post("/batches")
def create_batch(body: BatchBody, request: Request,
                 user: ResUsers = Depends(require_role("create")),
                 db: Session = Depends(get_db)):
    book_id = _resolve_book(db, request, body.book_id)
    b = payroll_service.create_batch(
        db, book_id=book_id, period=body.period, remark=body.remark,
        user_id=user.id, copy_from_last=body.copy_from_last)
    return {"ok": True, "batch": payroll_service.batch_to_dict(db, b, with_lines=True)}


class LineBody(BaseModel):
    employee_name: str
    id_card_tail: str | None = None
    gross_salary: str | float
    social_employee: str | float = "0"
    social_employer: str | float = "0"
    fund_employer: str | float = "0"
    iit: str | float | None = None
    remark: str | None = None


@router.post("/batches/{batch_id}/lines")
def add_line(batch_id: int, body: LineBody,
             user: ResUsers = Depends(require_role("write")),
             db: Session = Depends(get_db)):
    batch = db.get(PayrollBatch, batch_id)
    if batch is None or not batch.active:
        raise BizError("not_found", "工资批次不存在")
    line = payroll_service.add_line(db, batch, body.model_dump(), user_id=user.id)
    return {"ok": True, "line": payroll_service.line_to_dict(line),
            "batch": payroll_service.batch_to_dict(db, batch)}


class LineUpdateBody(BaseModel):
    employee_name: str | None = None
    id_card_tail: str | None = None
    gross_salary: str | float | None = None
    social_employee: str | float | None = None
    social_employer: str | float | None = None
    fund_employer: str | float | None = None
    iit: str | float | None = None
    remark: str | None = None


@router.put("/lines/{line_id}")
def update_line(line_id: int, body: LineUpdateBody,
                user: ResUsers = Depends(require_role("write")),
                db: Session = Depends(get_db)):
    line = payroll_service.update_line(db, line_id, body.dict(), user_id=user.id)
    batch = db.get(PayrollBatch, line.batch_id)
    return {"ok": True, "line": payroll_service.line_to_dict(line),
            "batch": payroll_service.batch_to_dict(db, batch)}


@router.delete("/lines/{line_id}")
def delete_line(line_id: int, user: ResUsers = Depends(require_role("delete")),
                db: Session = Depends(get_db)):
    payroll_service.delete_line(db, line_id, user_id=user.id)
    return {"ok": True}


@router.post("/batches/{batch_id}/recalc")
def recalc(batch_id: int, user: ResUsers = Depends(require_role("write")),
           db: Session = Depends(get_db)):
    batch = db.get(PayrollBatch, batch_id)
    if batch is None or not batch.active:
        raise BizError("not_found", "工资批次不存在")
    count = payroll_service.recalc_iit(db, batch)
    return {"ok": True, "recalculated": count,
            "batch": payroll_service.batch_to_dict(db, batch, with_lines=True)}


class ConfirmBody(BaseModel):
    move_date: str | None = None


@router.post("/batches/{batch_id}/confirm")
def confirm(batch_id: int, body: ConfirmBody | None = None,
            user: ResUsers = Depends(require_role("write")),
            db: Session = Depends(get_db)):
    mdate = date.fromisoformat(body.move_date[:10]) if (body and body.move_date) else None
    batch = payroll_service.confirm_batch(db, batch_id, user_id=user.id, move_date=mdate)
    return {"ok": True, "batch": payroll_service.batch_to_dict(db, batch, with_lines=True)}


@router.post("/batches/{batch_id}/mark-paid")
def mark_paid(batch_id: int, user: ResUsers = Depends(require_role("write")),
              db: Session = Depends(get_db)):
    batch = payroll_service.mark_paid(db, batch_id, user_id=user.id)
    return {"ok": True, "batch": payroll_service.batch_to_dict(db, batch)}


@router.get("/iit/preview")
def iit_preview(gross: str, social_employee: str = "0",
                user: ResUsers = Depends(require_login),
                db: Session = Depends(get_db)):
    """个税试算（新建员工行时实时预览）。"""
    return {"iit": str(compute_iit_monthly(gross, social_employee))}
