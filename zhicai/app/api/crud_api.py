# -*- coding: utf-8 -*-
"""通用 CRUD API（项目书 5.1 原则 1：模型驱动的动态路由）。

- 所有 book_scoped 模型自动注入当前账套过滤（Odoo record rules 思想）；
- 写操作自动记录字段级审计（Odoo mail.thread 思想）；
- 删除一律软删除（active=False）。
"""
import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import add_note, compute_changes, get_record_chatter, log_create, log_write
from ..core.book_context import ALL_BOOKS, cross_book_allowed, get_book_id
from ..core.db import get_db
from ..core.domain import parse_domain
from ..core.errors import BizError
from ..core.registry import REGISTRY
from ..modules.base.models import ResUsers
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/data", tags=["crud"])

# 只读系统字段（不接受前端写入）
PROTECTED_FIELDS = {"id", "create_uid", "create_date", "write_uid", "write_date", "active"}


def _serialize_value(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (list, dict)):
        return v
    return v


def _coerce_for_column(col, value):
    """按列类型把 JSON 值转成 Python 对象（date/datetime/Decimal；整数字符串转 int）。"""
    if value is None or value == "":
        return None
    t = type(col.type)
    if t.__name__ == "Date":
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return date.fromisoformat(str(value)[:10])
    if t.__name__ == "DateTime":
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))
    if t.__name__ in ("Numeric",):
        return Decimal(str(value)) if not isinstance(value, Decimal) else value
    if t.__name__ in ("Integer", "BigInteger") and isinstance(value, str):
        return int(value)
    return value


def _apply_values(model_cls, obj, values: dict):
    """把（已过滤的）字段值按列类型转换后写入对象。"""
    for k, v in values.items():
        col = model_cls.__table__.columns[k]
        setattr(obj, k, _coerce_for_column(col, v))


def _row_to_dict(model_cls, obj, rec_name: str | None = None) -> dict:
    data = {}
    for col in model_cls.__table__.columns:
        data[col.key] = _serialize_value(getattr(obj, col.key))
    if rec_name:
        data["_rec_name"] = rec_name
    return data


def _book_scope_clause(table: str, model_cls, book_id):
    """返回 (where 条件, 跨账套是否放行)。总览模式下仅白名单放行。"""
    if not getattr(model_cls, "_book_scoped", False):
        return None, True
    if book_id == ALL_BOOKS:
        views = REGISTRY.views_of(table)
        allowed = cross_book_allowed(table) or views.get("cross_book", False)
        if allowed:
            return None, True
        raise BizError("book_required", "该页面需要先选择一个客户账套（右上角切换器）")
    if table == "res_book":  # 账套表自身不过滤
        return None, True
    return model_cls.book_id == book_id, True


def _parse_order(order: str | None, model_cls):
    """order 形如 "code asc" / "create_date desc"，多字段逗号分隔。"""
    if not order:
        return None
    clauses = []
    for part in order.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        field = bits[0]
        direction = bits[1].lower() if len(bits) > 1 else "asc"
        if field not in model_cls.__table__.columns:
            raise BizError("order_field", f"排序字段不存在：{field}")
        col = model_cls.__table__.columns[field]
        clauses.append(col.desc() if direction == "desc" else col)
    return clauses


class RecordBody(BaseModel):
    values: dict


class NoteBody(BaseModel):
    body: str


@router.get("/{table}")
def list_records(
    table: str,
    request: Request,
    domain: str | None = Query(None, description="Odoo 风格 domain JSON"),
    limit: int = Query(80, ge=1, le=500),
    offset: int = Query(0, ge=0),
    order: str | None = Query(None),
    count_only: bool = Query(False),
    user: ResUsers = Depends(require_role("read")),
    db: Session = Depends(get_db),
):
    model_cls = REGISTRY.model(table)
    book_id = get_book_id(request)

    where = parse_domain(json.loads(domain) if domain else None, model_cls)
    scope, _ = _book_scope_clause(table, model_cls, book_id)

    q = select(model_cls)
    if where is not None:
        q = q.where(where)
    if scope is not None:
        q = q.where(scope)
    # 软删除默认隐藏
    q = q.where(model_cls.active.is_(True))

    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    if count_only:
        return {"total": total, "records": []}

    order_clauses = _parse_order(order, model_cls)
    if order_clauses:
        q = q.order_by(*order_clauses)
    else:
        q = q.order_by(model_cls.id)
    rows = db.execute(q.limit(limit).offset(offset)).scalars().all()

    rec_name_field = getattr(model_cls, "_rec_name", "name")
    return {
        "total": total,
        "records": [_row_to_dict(model_cls, r, getattr(r, rec_name_field, None)) for r in rows],
    }


@router.post("/{table}")
def create_record(
    table: str,
    body: RecordBody,
    request: Request,
    user: ResUsers = Depends(require_role("create")),
    db: Session = Depends(get_db),
):
    model_cls = REGISTRY.model(table)
    book_id = get_book_id(request)
    values = {k: v for k, v in (body.values or {}).items()
              if k in model_cls.__table__.columns and k not in PROTECTED_FIELDS}

    now = datetime.now()
    obj = model_cls()
    _apply_values(model_cls, obj, values)
    obj.create_uid = user.id
    obj.create_date = now
    obj.write_uid = user.id
    obj.write_date = now
    obj.active = True

    # 账套注入
    if getattr(model_cls, "_book_scoped", False):
        scope_ok = _book_scope_clause(table, model_cls, book_id)[1]
        if book_id == ALL_BOOKS:
            if "book_id" not in values:
                raise BizError("book_required", "新建记录需要先选择客户账套")
        elif "book_id" not in values:
            obj.book_id = book_id

    db.add(obj)
    db.flush()
    log_create(db, table, obj.id, user.id)
    db.flush()
    return {"ok": True, "record": _row_to_dict(model_cls, obj)}


@router.get("/{table}/{record_id}")
def get_record(
    table: str,
    record_id: int,
    request: Request,
    user: ResUsers = Depends(require_role("read")),
    db: Session = Depends(get_db),
):
    model_cls = REGISTRY.model(table)
    book_id = get_book_id(request)
    obj = db.get(model_cls, record_id)
    if obj is None or not obj.active:
        raise BizError("not_found", "记录不存在或已归档")
    scope, _ = _book_scope_clause(table, model_cls, book_id)
    if scope is not None and getattr(obj, "book_id", None) != book_id:
        raise BizError("not_found", "记录不存在或已归档")
    rec_name_field = getattr(model_cls, "_rec_name", "name")
    return {"record": _row_to_dict(model_cls, obj, getattr(obj, rec_name_field, None)),
            "chatter": get_record_chatter(db, table, record_id)}


@router.put("/{table}/{record_id}")
def update_record(
    table: str,
    record_id: int,
    body: RecordBody,
    request: Request,
    user: ResUsers = Depends(require_role("write")),
    db: Session = Depends(get_db),
):
    model_cls = REGISTRY.model(table)
    book_id = get_book_id(request)
    obj = db.get(model_cls, record_id)
    if obj is None or not obj.active:
        raise BizError("not_found", "记录不存在或已归档")
    scope, _ = _book_scope_clause(table, model_cls, book_id)
    if scope is not None and getattr(obj, "book_id", None) != book_id:
        raise BizError("not_found", "记录不存在或已归档")

    # 只允许改列字段；book_id 不允许换
    updates = {k: v for k, v in (body.values or {}).items()
               if k in model_cls.__table__.columns and k not in PROTECTED_FIELDS and k != "book_id"}
    changes = compute_changes(model_cls, obj, updates)
    _apply_values(model_cls, obj, updates)
    obj.write_uid = user.id
    obj.write_date = datetime.now()
    if changes:
        log_write(db, table, obj.id, user.id, changes)
    db.flush()
    return {"ok": True, "record": _row_to_dict(model_cls, obj), "changes": changes}


@router.delete("/{table}/{record_id}")
def delete_record(
    table: str,
    record_id: int,
    request: Request,
    user: ResUsers = Depends(require_role("delete")),
    db: Session = Depends(get_db),
):
    model_cls = REGISTRY.model(table)
    book_id = get_book_id(request)
    obj = db.get(model_cls, record_id)
    if obj is None:
        raise BizError("not_found", "记录不存在")
    scope, _ = _book_scope_clause(table, model_cls, book_id)
    if scope is not None and getattr(obj, "book_id", None) != book_id:
        raise BizError("not_found", "记录不存在")
    obj.active = False
    obj.write_uid = user.id
    obj.write_date = datetime.now()
    log_write(db, table, obj.id, user.id, [{"field": "active", "old": True, "new": False}])
    db.flush()
    return {"ok": True}


@router.post("/{table}/{record_id}/note")
def add_record_note(
    table: str,
    record_id: int,
    body: NoteBody,
    user: ResUsers = Depends(require_login),
    db: Session = Depends(get_db),
):
    if not (body.body or "").strip():
        raise BizError("note_empty", "留言内容不能为空")
    add_note(db, table, record_id, user.id, body.body.strip())
    db.flush()
    return {"ok": True, "chatter": get_record_chatter(db, table, record_id)}


@router.get("/{table}/{record_id}/chatter")
def record_chatter(
    table: str,
    record_id: int,
    user: ResUsers = Depends(require_login),
    db: Session = Depends(get_db),
):
    return {"chatter": get_record_chatter(db, table, record_id)}
