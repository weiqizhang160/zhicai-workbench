# -*- coding: utf-8 -*-
"""任务 API（M5，项目书 7.4）：任务看板 / 列表 / 新建 / 状态流转。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.book_context import ALL_BOOKS, get_book_id
from ..core.db import get_db
from ..core.errors import BizError
from ..modules.base.models import ResUsers
from ..modules.res_partner.models import ResBook
from ..modules.tasks import service as tasks_service
from ..modules.tasks.models import TaskTask
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def _resolve_book_id(request: Request, explicit: int | None) -> int | None:
    """任务创建/查询时的账套上下文：总览模式可建全局任务。"""
    if explicit is not None:
        return explicit
    bid = get_book_id(request)
    return None if bid == ALL_BOOKS else bid


@router.get("")
def list_tasks(request: Request,
               state: str | None = Query(None),
               priority: str | None = Query(None),
               overdue_only: bool = Query(False),
               limit: int = Query(500, ge=1, le=2000),
               user: ResUsers = Depends(require_login),
               db: Session = Depends(get_db)):
    """任务列表：总览=全部；指定账套=该账套 + 全局任务。"""
    bid = get_book_id(request)
    book_id = None if bid == ALL_BOOKS else bid
    rows = tasks_service.list_tasks(db, book_id, state=state, priority=priority,
                                    overdue_only=overdue_only, limit=limit)
    return {"items": [tasks_service.task_to_dict(db, t) for t in rows]}


@router.get("/kanban")
def kanban(request: Request, user: ResUsers = Depends(require_login),
           db: Session = Depends(get_db)):
    """看板数据：按 state 分栏（todo/doing/done/cancelled）。"""
    bid = get_book_id(request)
    book_id = None if bid == ALL_BOOKS else bid
    rows = tasks_service.list_tasks(db, book_id)
    cols = {s: [] for s in tasks_service.TASK_STATES}
    for t in rows:
        cols.setdefault(t.state, []).append(tasks_service.task_to_dict(db, t))
    return {"columns": [
        {"state": s, "items": cols[s]} for s in tasks_service.TASK_STATES
    ]}


class TaskBody(BaseModel):
    book_id: int | None = None
    title: str
    description: str = ""
    due_date: str | None = None
    priority: str = "normal"
    state: str = "todo"


@router.post("")
def create_task(body: TaskBody, request: Request,
                user: ResUsers = Depends(require_role("create")),
                db: Session = Depends(get_db)):
    if not (body.title or "").strip():
        raise BizError("title_required", "任务标题不能为空")
    book_id = _resolve_book_id(request, body.book_id)
    if book_id is not None:
        book = db.get(ResBook, book_id)
        if book is None or not book.active:
            raise BizError("not_found", "客户账套不存在")
    now = datetime.now()
    t = TaskTask(
        book_id=book_id,
        title=body.title.strip(),
        description=body.description or None,
        due_date=date.fromisoformat(body.due_date[:10]) if body.due_date else None,
        priority=body.priority if body.priority in ("low", "normal", "high", "urgent") else "normal",
        state=body.state if body.state in tasks_service.TASK_STATES else "todo",
        reminder_sent=False,
        create_uid=user.id, create_date=now, write_uid=user.id, write_date=now,
        active=True,
    )
    db.add(t)
    db.flush()
    return {"ok": True, "task": tasks_service.task_to_dict(db, t)}


class TaskUpdateBody(BaseModel):
    title: str | None = None
    description: str | None = None
    due_date: str | None = None
    priority: str | None = None
    book_id: int | None = None


@router.put("/{task_id}")
def update_task(task_id: int, body: TaskUpdateBody,
                user: ResUsers = Depends(require_role("write")),
                db: Session = Depends(get_db)):
    t = db.get(TaskTask, task_id)
    if t is None or not t.active:
        raise BizError("not_found", "任务不存在")
    if body.title is not None:
        t.title = body.title.strip()
    if body.description is not None:
        t.description = body.description
    if body.due_date is not None:
        t.due_date = date.fromisoformat(body.due_date[:10]) if body.due_date else None
    if body.priority is not None:
        t.priority = body.priority if body.priority in ("low", "normal", "high", "urgent") else t.priority
    if body.book_id is not None:
        t.book_id = body.book_id
    t.write_uid = user.id
    t.write_date = datetime.now()
    db.flush()
    return {"ok": True, "task": tasks_service.task_to_dict(db, t)}


class StateBody(BaseModel):
    state: str


@router.post("/{task_id}/state")
def set_state(task_id: int, body: StateBody,
              user: ResUsers = Depends(require_role("write")),
              db: Session = Depends(get_db)):
    t = tasks_service.set_task_state(db, task_id, body.state)
    t.write_uid = user.id
    t.write_date = datetime.now()
    db.flush()
    return {"ok": True, "task": tasks_service.task_to_dict(db, t)}


@router.delete("/{task_id}")
def delete_task(task_id: int, user: ResUsers = Depends(require_role("delete")),
                db: Session = Depends(get_db)):
    t = db.get(TaskTask, task_id)
    if t is None or not t.active:
        raise BizError("not_found", "任务不存在")
    t.active = False
    t.write_uid = user.id
    t.write_date = datetime.now()
    db.flush()
    return {"ok": True}
