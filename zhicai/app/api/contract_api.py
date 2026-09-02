# -*- coding: utf-8 -*-
"""合同与收费 API（M5，项目书 7.4）：合同 / 收费计划 / 收款登记 / 应收报表 / 扫描。"""
import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.book_context import ALL_BOOKS, get_book_id
from ..core.db import get_db
from ..core.errors import BizError
from ..core.sequence import ensure_sequence, next_number
from ..modules.base.models import ResUsers
from ..modules.contract import service as contract_service
from ..modules.contract.models import ContractAgreement, ContractFeeItem
from ..modules.res_partner.models import ResBook
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/contract", tags=["contract"])

CONTRACT_SEQ = "contract.agreement"


def _ensure_seq(db: Session) -> None:
    ensure_sequence(db, CONTRACT_SEQ, "HT", name="代账合同编号", padding=4)


def _agreement_to_dict(db: Session, ag: ContractAgreement) -> dict:
    book = db.get(ResBook, ag.book_id) if ag.book_id else None
    scope = None
    if ag.service_scope:
        try:
            scope = json.loads(ag.service_scope)
        except (ValueError, TypeError):
            scope = ag.service_scope
    return {
        "id": ag.id, "book_id": ag.book_id,
        "book_name": book.short_name if book else None,
        "contract_no": ag.contract_no,
        "sign_date": ag.sign_date.isoformat() if ag.sign_date else None,
        "start_date": ag.start_date.isoformat() if ag.start_date else None,
        "end_date": ag.end_date.isoformat() if ag.end_date else None,
        "service_scope": scope,
        "fee_type": ag.fee_type,
        "fee_amount": str(ag.fee_amount or 0),
        "payer_name": ag.payer_name,
        "state": ag.state,
        "expiring": ag.is_expiring,
        "remark": ag.remark,
    }


def _fee_to_dict(db: Session, it: ContractFeeItem) -> dict:
    book = db.get(ResBook, it.book_id) if it.book_id else None
    return {
        "id": it.id, "agreement_id": it.agreement_id,
        "book_id": it.book_id,
        "book_name": book.short_name if book else None,
        "period": it.period,
        "amount": str(it.amount or 0),
        "due_date": it.due_date.isoformat() if it.due_date else None,
        "state": it.state,
        "overdue": it.is_overdue,
        "paid_date": it.paid_date.isoformat() if it.paid_date else None,
        "paid_amount": (str(it.paid_amount) if it.paid_amount is not None else None),
        "invoice_no": it.invoice_no,
    }


# ==================== 合同 ====================

@router.get("/agreements")
def list_agreements(
    state: str | None = Query(None),
    book_id: int | None = Query(None),
    expiring_only: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    user: ResUsers = Depends(require_login),
    db: Session = Depends(get_db),
):
    """合同列表（总览模式跨账套）。"""
    q = select(ContractAgreement).where(ContractAgreement.active.is_(True))
    if state:
        q = q.where(ContractAgreement.state == state)
    if book_id:
        q = q.where(ContractAgreement.book_id == book_id)
    rows = db.execute(q.order_by(ContractAgreement.id.desc()).limit(limit)).scalars().all()
    if expiring_only:
        rows = [r for r in rows if r.is_expiring]
    return {"agreements": [_agreement_to_dict(db, r) for r in rows]}


class AgreementBody(BaseModel):
    book_id: int | None = None
    sign_date: str | None = None
    start_date: str
    end_date: str
    service_scope: list[str] | None = None
    fee_type: str = "monthly"
    fee_amount: str
    payer_name: str = ""
    state: str = "active"
    remark: str = ""


@router.post("/agreements")
def create_agreement(body: AgreementBody, request: Request,
                     user: ResUsers = Depends(require_role("create")),
                     db: Session = Depends(get_db)):
    """新建合同：生成编号 + 自动生成收费计划。"""
    _ensure_seq(db)
    book_id = body.book_id or (get_book_id(request) if get_book_id(request) != ALL_BOOKS else None)
    if book_id is None:
        raise BizError("book_required", "新建合同需要先选择客户账套，或指定 book_id")
    book = db.get(ResBook, book_id)
    if book is None or not book.active:
        raise BizError("not_found", "客户账套不存在")

    if body.fee_type not in ("monthly", "quarterly", "annual"):
        raise BizError("fee_type_invalid", "收费周期必须是 monthly/quarterly/annual 之一")
    if body.state not in ("active", "expired", "terminated"):
        raise BizError("state_invalid", "合同状态必须是 active/expired/terminated 之一")

    now = datetime.now()
    ag = ContractAgreement(
        book_id=book_id,
        contract_no=next_number(db, CONTRACT_SEQ),
        sign_date=date.fromisoformat(body.sign_date[:10]) if body.sign_date else date.today(),
        start_date=date.fromisoformat(body.start_date[:10]),
        end_date=date.fromisoformat(body.end_date[:10]),
        service_scope=json.dumps(body.service_scope, ensure_ascii=False)
        if body.service_scope else None,
        fee_type=body.fee_type,
        fee_amount=Decimal(str(body.fee_amount or 0)),
        payer_name=body.payer_name or None,
        state=body.state,
        remark=body.remark or None,
        create_uid=user.id, create_date=now, write_uid=user.id, write_date=now,
        active=True,
    )
    db.add(ag)
    db.flush()
    gen = contract_service.generate_fee_items(db, ag)
    return {"ok": True, "agreement": _agreement_to_dict(db, ag), "fee": gen}


@router.get("/agreements/{agreement_id}")
def get_agreement(agreement_id: int, user: ResUsers = Depends(require_login),
                  db: Session = Depends(get_db)):
    ag = db.get(ContractAgreement, agreement_id)
    if ag is None or not ag.active:
        raise BizError("not_found", "合同不存在")
    items = db.execute(
        select(ContractFeeItem).where(
            ContractFeeItem.agreement_id == agreement_id,
            ContractFeeItem.active.is_(True),
        ).order_by(ContractFeeItem.period)
    ).scalars().all()
    return {"agreement": _agreement_to_dict(db, ag),
            "fee_items": [_fee_to_dict(db, i) for i in items]}


@router.post("/agreements/{agreement_id}/fee-items/generate")
def generate_agreement_fee(agreement_id: int,
                           user: ResUsers = Depends(require_role("create")),
                           db: Session = Depends(get_db)):
    ag = db.get(ContractAgreement, agreement_id)
    if ag is None or not ag.active:
        raise BizError("not_found", "合同不存在")
    return {"ok": True, **contract_service.generate_fee_items(db, ag)}


# ==================== 收费计划 / 收款登记 ====================

class CollectBody(BaseModel):
    fee_item_ids: list[int]
    paid_date: str | None = None
    paid_amounts: dict[int, str] | None = None


@router.post("/fee-items/bulk-collect")
def bulk_collect(body: CollectBody, user: ResUsers = Depends(require_role("write")),
                 db: Session = Depends(get_db)):
    """批量收款登记：月末一键收 60 家（项目书 7.4 一键场景）。"""
    pd_ = date.fromisoformat(body.paid_date[:10]) if body.paid_date else None
    result = contract_service.collect_fee_items(db, body.fee_item_ids,
                                                paid_date=pd_,
                                                paid_amounts=body.paid_amounts)
    return {"ok": True, **result}


class SingleCollectBody(BaseModel):
    paid_date: str | None = None
    paid_amount: str | None = None


@router.post("/fee-items/{fee_item_id}/collect")
def collect_one(fee_item_id: int, body: SingleCollectBody | None = None,
                user: ResUsers = Depends(require_role("write")),
                db: Session = Depends(get_db)):
    amounts = {}
    if body and body.paid_amount is not None:
        amounts[fee_item_id] = body.paid_amount
    pd_ = date.fromisoformat(body.paid_date[:10]) if (body and body.paid_date) else None
    contract_service.collect_fee_items(db, [fee_item_id], paid_date=pd_, paid_amounts=amounts)
    it = db.get(ContractFeeItem, fee_item_id)
    return {"ok": True, "item": _fee_to_dict(db, it)}


class InvoiceBody(BaseModel):
    invoice_no: str | None = None


@router.post("/fee-items/{fee_item_id}/invoice")
def mark_invoiced(fee_item_id: int, body: InvoiceBody | None = None,
                  user: ResUsers = Depends(require_role("write")),
                  db: Session = Depends(get_db)):
    it = contract_service.mark_invoiced(db, fee_item_id, body.invoice_no if body else None)
    return {"ok": True, "item": _fee_to_dict(db, it)}


@router.get("/fee-items")
def list_fee_items(
    period: str | None = Query(None),
    state: str | None = Query(None),
    book_id: int | None = Query(None),
    overdue_only: bool = Query(False),
    limit: int = Query(500, ge=1, le=2000),
    user: ResUsers = Depends(require_login),
    db: Session = Depends(get_db),
):
    """收费计划列表（总览模式跨账套，供收款登记勾选）。"""
    q = select(ContractFeeItem).where(ContractFeeItem.active.is_(True))
    if period:
        q = q.where(ContractFeeItem.period == period)
    if state:
        q = q.where(ContractFeeItem.state == state)
    if book_id:
        q = q.where(ContractFeeItem.book_id == book_id)
    rows = db.execute(
        q.order_by(ContractFeeItem.due_date, ContractFeeItem.book_id,
                   ContractFeeItem.id).limit(limit)
    ).scalars().all()
    if overdue_only:
        rows = [r for r in rows if r.is_overdue]
    return {"items": [_fee_to_dict(db, r) for r in rows]}


# ==================== 应收报表 ====================

@router.get("/report/receivable")
def receivable_report(book_id: int | None = Query(None),
                      user: ResUsers = Depends(require_login),
                      db: Session = Depends(get_db)):
    return contract_service.receivable_report(db, book_id)


# ==================== 逾期 / 续约扫描 ====================

@router.post("/scan")
def scan(user: ResUsers = Depends(require_role("write")), db: Session = Depends(get_db)):
    return {"ok": True, **contract_service.scan_overdue_and_renewal(db, user.id)}
