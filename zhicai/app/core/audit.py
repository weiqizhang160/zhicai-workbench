# -*- coding: utf-8 -*-
"""通用审计日志与备注（对标 Odoo mail.thread 的 chatter，项目书 5.2/6.2）。"""
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..modules.base.models import AuditLog, NoteMessage


def log_create(db: Session, model: str, record_id: int, user_id: int | None):
    db.add(AuditLog(model=model, record_id=record_id, user_id=user_id,
                    action="create", changes=None))


def log_write(db: Session, model: str, record_id: int, user_id: int | None, changes: list[dict]):
    """changes: [{field, old, new}]（值已 JSON 安全化）。"""
    db.add(AuditLog(model=model, record_id=record_id, user_id=user_id,
                    action="write", changes=json.dumps(changes, ensure_ascii=False)))


def log_action(db: Session, model: str, record_id: int, user_id: int | None, action: str, message: str = ""):
    db.add(AuditLog(model=model, record_id=record_id, user_id=user_id,
                    action=action, changes=json.dumps({"message": message}, ensure_ascii=False)))


def compute_changes(model_cls, obj, updates: dict) -> list[dict]:
    """对比对象当前值与更新字典，产出字段级变更记录（JSON 安全）。"""
    changes = []
    for field, new in updates.items():
        if not hasattr(model_cls, field):
            continue
        old = getattr(obj, field, None)
        if old == new:
            continue
        changes.append({
            "field": field,
            "old": _json_safe(old),
            "new": _json_safe(new),
        })
    return changes


def _json_safe(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, (list, dict)):
        return v if _is_jsonable(v) else str(v)
    return str(v)


def _is_jsonable(v) -> bool:
    try:
        json.dumps(v, ensure_ascii=False)
        return True
    except (TypeError, ValueError):
        return False


def add_note(db: Session, model: str, record_id: int, user_id: int | None, body: str):
    db.add(NoteMessage(model=model, record_id=record_id, user_id=user_id, body=body))


def get_record_chatter(db: Session, model: str, record_id: int, limit: int = 100) -> list[dict]:
    """取记录的活动日志 + 留言，按时间倒序合并（FormView 底部面板数据源）。"""
    logs = db.execute(
        select(AuditLog)
        .where(AuditLog.model == model, AuditLog.record_id == record_id)
        .order_by(AuditLog.id.desc()).limit(limit)
    ).scalars().all()
    notes = db.execute(
        select(NoteMessage)
        .where(NoteMessage.model == model, NoteMessage.record_id == record_id)
        .order_by(NoteMessage.id.desc()).limit(limit)
    ).scalars().all()
    items = []
    for lg in logs:
        items.append({
            "kind": "log", "id": f"log-{lg.id}", "action": lg.action,
            "user_id": lg.user_id, "created_at": lg.created_at.isoformat(sep=" ") if lg.created_at else None,
            "changes": json.loads(lg.changes) if lg.changes else [],
        })
    for nt in notes:
        items.append({
            "kind": "note", "id": f"note-{nt.id}", "body": nt.body,
            "user_id": nt.user_id, "created_at": nt.created_at.isoformat(sep=" ") if nt.created_at else None,
        })
    items.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return items
