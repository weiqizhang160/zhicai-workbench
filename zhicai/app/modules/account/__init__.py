# -*- coding: utf-8 -*-
"""account 模块注册（M1：科目 + 账簿；M2：凭证 + 分录 + 期间锁 + 税率）。"""
from ...core.registry import ModuleDescriptor
from .models import (
    AccountAccount,
    AccountJournal,
    AccountMove,
    AccountMoveLine,
    AccountPeriodClose,
    AccountTax,
)
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="account",
        label="记账",
        depends=["base", "res_partner"],
        menu=[
            # —— 基础设置 ——
            {"key": "accounts", "label": "会计科目", "table": "account_account", "icon": "Notebook",
             "group": "记账"},
            {"key": "journals", "label": "账簿设置", "table": "account_journal", "icon": "Tickets",
             "group": "记账"},
            {"key": "taxes", "label": "税率设置", "table": "account_tax", "icon": "Coin",
             "group": "记账"},
            # —— 记账作业（定制页，route 优先于 table） ——
            {"key": "moves", "label": "记账凭证", "table": "account_move", "icon": "Document",
             "group": "记账作业"},
            {"key": "move_entry", "label": "凭证录入", "route": "#/move/new", "icon": "EditPen",
             "group": "记账作业"},
            # —— 查询与报表（定制页） ——
            {"key": "ledger", "label": "账簿查询", "route": "#/ledger", "icon": "Reading",
             "group": "账簿报表"},
            {"key": "reports", "label": "财务报表", "route": "#/reports", "icon": "DataAnalysis",
             "group": "账簿报表"},
        ],
        models={
            "account_account": AccountAccount,
            "account_journal": AccountJournal,
            "account_move": AccountMove,
            "account_move_line": AccountMoveLine,
            "account_period_close": AccountPeriodClose,
            "account_tax": AccountTax,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=None,  # 科目模板按账套初始化时克隆，无全局种子
    )
