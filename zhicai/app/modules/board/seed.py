# -*- coding: utf-8 -*-
"""board 模块种子：默认 6 张仪表盘卡片（项目书 7.2）。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BoardCard

DEFAULT_CARDS = [
    # (card_key, position)
    ("overview", 1),
    ("decl_alert", 2),
    ("overdue", 3),
    ("todo_tasks", 4),
    ("fee_month", 5),
    ("client_progress", 6),
]


def seed_cards(db: Session) -> int:
    """写入缺失的默认卡片配置（按 card_key 幂等）。"""
    existed = {
        c[0] for c in db.execute(
            select(BoardCard.card_key).where(BoardCard.active.is_(True))
        ).all()
    }
    created = 0
    for key, pos in DEFAULT_CARDS:
        if key in existed:
            continue
        db.add(BoardCard(card_key=key, position=pos, enabled=True, active=True))
        created += 1
    if created:
        db.flush()
    return created
