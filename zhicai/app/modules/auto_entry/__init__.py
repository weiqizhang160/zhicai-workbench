# -*- coding: utf-8 -*-
"""auto_entry 模块注册（M3）：自动记账规则引擎，本项目核心卖点。"""
from ...core.registry import ModuleDescriptor
from .models import AutoEntryLog, AutoEntryRule
from .seed_rules import seed_rules
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="auto_entry",
        label="自动记账",
        depends=["base", "res_partner", "account", "invoice", "bank"],
        menu=[
            {"key": "auto_workbench", "label": "批量执行", "route": "#/auto-entry",
             "icon": "MagicStick", "group": "自动记账"},
            {"key": "auto_rules", "label": "记账规则", "table": "auto_entry_rule",
             "icon": "Setting", "group": "自动记账"},
            {"key": "auto_logs", "label": "执行日志", "table": "auto_entry_log",
             "icon": "Document", "group": "自动记账"},
        ],
        models={
            "auto_entry_rule": AutoEntryRule,
            "auto_entry_log": AutoEntryLog,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=seed_rules,   # 为所有已有账套补建种子规则（幂等）
    )
