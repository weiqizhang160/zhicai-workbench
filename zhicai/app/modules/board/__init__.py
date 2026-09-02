# -*- coding: utf-8 -*-
"""board 模块注册（M5）：首页仪表盘卡片配置（项目书 6.13 / 7.2）。"""
from ...core.registry import ModuleDescriptor
from .models import BoardCard
from .seed import seed_cards
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="board",
        label="工作台",
        depends=["base"],
        menu=[
            {"key": "board_cards", "label": "仪表盘卡片", "table": "board_card",
             "icon": "Grid", "group": "系统"},
        ],
        models={
            "board_card": BoardCard,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=seed_cards,
    )
