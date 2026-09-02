# -*- coding: utf-8 -*-
"""tasks 模块业务逻辑（项目书 7.4）：任务列表过滤 / 看板分组 / 状态流转。"""
from datetime import date

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ..res_partner.models import ResBook
from .models import TaskTask

TASK_STATES = ["todo", "doing", "done", "cancelled"]

# 优先级排序权重：urgent 最前，其次 high/normal/low，未知值排最后
_PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
_PRIORITY_CASE = case({p: r for p, r in _PRIORITY_RANK.items()},
                      value=TaskTask.priority, else_=99)


def list_tasks(db: Session, book_id: int | str | None = None, *,
               state: str | None = None, states: list[str] | None = None,
               priority: str | None = None,
               overdue_only: bool = False, limit: int = 500) -> list[TaskTask]:
    """任务列表。

    book_id=None（总览模式）→ 全部任务；
    book_id=int → 该账套任务 + 全局任务（book_id IS NULL）。

    排序：优先级（urgent/high 优先）→ 到期日（空排最后）→ id。
    这样「待办任务」顶部始终是最紧急的事项，不会被无到期日任务挤出。
    """
    q = select(TaskTask).where(TaskTask.active.is_(True))
    if book_id is None:
        pass
    else:
        q = q.where((TaskTask.book_id == book_id) | (TaskTask.book_id.is_(None)))
    if state:
        q = q.where(TaskTask.state == state)
    if states:
        q = q.where(TaskTask.state.in_(states))
    if priority:
        q = q.where(TaskTask.priority == priority)
    if overdue_only:
        q = q.where(TaskTask.due_date < date.today(),
                    TaskTask.state.in_(["todo", "doing"]))
    q = q.order_by(_PRIORITY_CASE, TaskTask.due_date.is_(None),
                   TaskTask.due_date, TaskTask.id)
    return db.execute(q.limit(limit)).scalars().all()


def task_to_dict(db: Session, t: TaskTask) -> dict:
    book = db.get(ResBook, t.book_id) if t.book_id else None
    return {
        "id": t.id, "book_id": t.book_id,
        "book_name": book.short_name if book else None,
        "title": t.title, "description": t.description,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "priority": t.priority, "state": t.state,
        "source_model": t.source_model, "source_id": t.source_id,
        "reminder_sent": t.reminder_sent,
    }


def set_task_state(db: Session, task_id: int, state: str) -> TaskTask:
    if state not in TASK_STATES:
        raise BizError("state_invalid", f"状态必须是 {TASK_STATES} 之一")
    t = db.get(TaskTask, task_id)
    if t is None or not t.active:
        raise BizError("not_found", "任务不存在")
    t.state = state
    db.flush()
    return t
