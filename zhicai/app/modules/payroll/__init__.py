# -*- coding: utf-8 -*-
"""payroll 模块注册（M6）：工资社保。"""
from ...core.registry import ModuleDescriptor
from .iit import ensure_brackets
from .models import PayrollBatch, PayrollLine
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="payroll",
        label="工资社保",
        depends=["base", "res_partner", "account"],
        menu=[
            # 批次 + 员工行 + 凭证生成是定制流程，用定制页
            {"key": "payroll", "label": "工资表", "route": "#/payroll",
             "icon": "Coin", "group": "工资"},
        ],
        models={
            "payroll_batch": PayrollBatch,
            "payroll_line": PayrollLine,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=ensure_brackets,
    )
