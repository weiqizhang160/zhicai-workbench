# -*- coding: utf-8 -*-
"""tax_decl 模块注册（M4）：申报台账与日历（防漏报核心）。

系统只做登记、计算底稿与官网导航，**不做自动申报**（政策安全原因，项目书 7.9）。
"""
from ...core.registry import ModuleDescriptor
from .models import TaxCalendarRule, TaxDeclItem
from .seed_rules import seed_calendar_rules
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="tax_decl",
        label="税务申报",
        depends=["base", "res_partner", "account", "invoice"],
        menu=[
            # 申报日历是总览页（跨全部客户），用定制页
            {"key": "tax_calendar", "label": "申报日历", "route": "#/tax-decl",
             "icon": "Calendar", "group": "税务申报"},
            {"key": "tax_rules", "label": "征期规则", "table": "tax_calendar_rule",
             "icon": "Timer", "group": "税务申报"},
        ],
        models={
            "tax_calendar_rule": TaxCalendarRule,
            "tax_decl_item": TaxDeclItem,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=seed_calendar_rules,
    )
