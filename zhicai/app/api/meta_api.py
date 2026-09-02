# -*- coding: utf-8 -*-
"""元数据 API：菜单 / 模型描述（模型驱动 UI 的数据源，项目书 5.1）。"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.registry import REGISTRY
from ..modules.base.models import ResUsers
from ..modules.res_partner.models import ResBook
from .deps import require_login

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


@router.get("/menu")
def menu(_user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    """左侧导航菜单（模块注册表驱动——装了什么模块显示什么，Odoo 同款机制）。

    foreign_only 菜单项（外贸专区）仅当至少一个账套 is_foreign_trade=true 时显示
    （项目书 7.1 / 7.10 DoD：非外贸客户看不到外贸菜单）。
    """
    menus = REGISTRY.menus()
    if any(m.get("foreign_only") for m in menus):
        has_ft = db.execute(
            select(ResBook.id).where(
                ResBook.active.is_(True), ResBook.is_foreign_trade.is_(True))
            .limit(1)
        ).scalar_one_or_none() is not None
        if not has_ft:
            menus = [m for m in menus if not m.get("foreign_only")]
    return {"menus": menus}


@router.get("/models")
def models(_user: ResUsers = Depends(require_login)):
    items = []
    for table in REGISTRY._models:
        d = REGISTRY.describe_model(table)
        items.append({"table": d["table"], "label": d["label"], "module": d["module"],
                      "book_scoped": d["book_scoped"]})
    return {"models": items}


@router.get("/{table}")
def describe(table: str, _user: ResUsers = Depends(require_login)):
    """模型完整描述：字段元数据 + 视图配置 + 记录数。"""
    return REGISTRY.describe_model(table)
