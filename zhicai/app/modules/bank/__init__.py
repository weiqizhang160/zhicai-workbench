# -*- coding: utf-8 -*-
"""bank 模块注册（M3）：银行流水导入与对账。"""
from ...core.registry import ModuleDescriptor
from .models import BankStatement, BankStatementLine
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="bank",
        label="银行",
        depends=["base", "res_partner", "account"],
        menu=[
            {"key": "bank_reconcile", "label": "银行对账", "route": "#/bank",
             "icon": "BankCard", "group": "票据与银行"},
        ],
        models={
            "bank_statement": BankStatement,
            "bank_statement_line": BankStatementLine,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=None,
    )
