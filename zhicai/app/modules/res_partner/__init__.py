# -*- coding: utf-8 -*-
"""res_partner 模块注册：客户账套 + 往来单位。"""
from ...core.registry import ModuleDescriptor
from .models import ResBook, ResPartner
from .views import FIELD_META, VIEWS
from . import seed as seed_mod


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="res_partner",
        label="客户与合同",
        depends=["base"],
        menu=[
            {"key": "books", "label": "客户管理", "table": "res_book", "icon": "OfficeBuilding",
             "group": "客户与合同"},
            {"key": "partners", "label": "往来单位", "table": "res_partner", "icon": "Connection",
             "group": "客户与合同"},
        ],
        models={
            "res_book": ResBook,
            "res_partner": ResPartner,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=seed_mod.seed,
    )
