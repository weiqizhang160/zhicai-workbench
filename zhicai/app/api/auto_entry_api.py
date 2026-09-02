# -*- coding: utf-8 -*-
"""自动记账 API（M3，项目书 7.7）：规则 CRUD / 待处理预览 / 批量执行 / 日志。"""
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.book_context import ALL_BOOKS, get_book_id
from ..core.db import get_db
from ..core.errors import BizError
from ..modules.auto_entry import engine
from ..modules.auto_entry.models import AutoEntryLog, AutoEntryRule
from ..modules.base.models import ResUsers
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/ae", tags=["auto_entry"])


def _require_book(request: Request) -> int:
    book_id = get_book_id(request)
    if book_id == ALL_BOOKS or not isinstance(book_id, int):
        raise BizError("book_required", "请先在右上角选择一个客户账套")
    return book_id


# ==================== 规则 ====================

class RuleBody(BaseModel):
    name: str
    trigger: str
    match_condition: str | dict | None = None
    journal_code: str = "记"
    line_template: str | list
    priority: int = 100
    enabled: bool = True


def _rule_to_dict(r: AutoEntryRule) -> dict:
    import json
    return {
        "id": r.id, "name": r.name, "trigger": r.trigger,
        "match_condition": r.match_condition, "journal_code": r.journal_code,
        "line_template": r.line_template, "priority": r.priority,
        "enabled": r.enabled, "is_seed": r.is_seed, "seed_key": r.seed_key,
        "book_id": r.book_id,
    }


@router.get("/rules")
def list_rules(request: Request, trigger: str | None = Query(None),
               user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    book_id = _require_book(request)
    q = select(AutoEntryRule).where(
        AutoEntryRule.active.is_(True),
        (AutoEntryRule.book_id == book_id) | (AutoEntryRule.book_id.is_(None)))
    if trigger:
        q = q.where(AutoEntryRule.trigger == trigger)
    rows = db.execute(q.order_by(AutoEntryRule.priority, AutoEntryRule.id)).scalars().all()
    return {"rules": [_rule_to_dict(r) for r in rows]}


@router.post("/rules")
def create_rule(body: RuleBody, request: Request,
                user: ResUsers = Depends(require_role("create")),
                db: Session = Depends(get_db)):
    import json
    book_id = _require_book(request)
    rule = AutoEntryRule(
        name=body.name, trigger=body.trigger,
        match_condition=json.dumps(body.match_condition or {}, ensure_ascii=False)
        if not isinstance(body.match_condition, str) else body.match_condition,
        journal_code=body.journal_code or "记",
        line_template=json.dumps(body.line_template, ensure_ascii=False)
        if not isinstance(body.line_template, str) else body.line_template,
        priority=body.priority, enabled=body.enabled,
        is_seed=False, book_id=book_id, active=True)
    db.add(rule)
    db.flush()
    return {"ok": True, "rule": _rule_to_dict(rule)}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleBody,
                user: ResUsers = Depends(require_role("write")),
                db: Session = Depends(get_db)):
    import json
    rule = db.get(AutoEntryRule, rule_id)
    if rule is None or not rule.active:
        raise BizError("not_found", "规则不存在")
    rule.name = body.name
    rule.trigger = body.trigger
    rule.match_condition = (json.dumps(body.match_condition or {}, ensure_ascii=False)
                            if not isinstance(body.match_condition, str) else body.match_condition)
    rule.journal_code = body.journal_code or "记"
    rule.line_template = (json.dumps(body.line_template, ensure_ascii=False)
                          if not isinstance(body.line_template, str) else body.line_template)
    rule.priority = body.priority
    rule.enabled = body.enabled
    db.flush()
    return {"ok": True, "rule": _rule_to_dict(rule)}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, user: ResUsers = Depends(require_role("delete")),
                db: Session = Depends(get_db)):
    rule = db.get(AutoEntryRule, rule_id)
    if rule is None:
        raise BizError("not_found", "规则不存在")
    rule.active = False
    db.flush()
    return {"ok": True}


# ==================== 批量执行工作台 ====================

@router.get("/pending")
def pending_list(request: Request, period: str | None = Query(None),
                 source_models: str | None = Query(None,
                                                   description="逗号分隔：invoice_bill,bank_statement_line"),
                 user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    """列出未生成凭证的源单据，逐条给出命中规则与分录预览。"""
    book_id = _require_book(request)
    models = source_models.split(",") if source_models else None
    items = engine.collect_pending(db, book_id, period, models)
    matched = [i for i in items if i["matched"]]
    return {
        "total": len(items), "matched": len(matched),
        "unmatched": len(items) - len(matched),
        "items": items,
    }


class ExecItem(BaseModel):
    source_model: str
    source_id: int
    rule_id: int | None = None
    lines: list[dict] | None = None      # 前端可改科目后回传覆盖


class ExecBody(BaseModel):
    items: list[ExecItem]


@router.post("/execute")
def execute(body: ExecBody, request: Request,
            user: ResUsers = Depends(require_role("create")),
            db: Session = Depends(get_db)):
    """批量生成 draft 凭证（幂等：已处理的源单据会跳过）。"""
    book_id = _require_book(request)
    if not body.items:
        raise BizError("no_items", "请先勾选要执行的单据")
    return {"ok": True, **engine.execute_batch(
        db, book_id, [it.model_dump() for it in body.items], user.id)}


# ==================== 日志 ====================

@router.get("/logs")
def list_logs(request: Request, result: str | None = Query(None),
              limit: int = Query(100, ge=1, le=500),
              user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    book_id = _require_book(request)
    q = select(AutoEntryLog).where(AutoEntryLog.book_id == book_id,
                                   AutoEntryLog.active.is_(True))
    if result:
        q = q.where(AutoEntryLog.result == result)
    rows = db.execute(q.order_by(AutoEntryLog.id.desc()).limit(limit)).scalars().all()
    return {"logs": [{
        "id": r.id, "rule_id": r.rule_id, "source_model": r.source_model,
        "source_id": r.source_id, "result": r.result, "move_id": r.move_id,
        "message": r.message,
        "created_at": r.created_at.isoformat(sep=" ") if r.created_at else None,
    } for r in rows]}
