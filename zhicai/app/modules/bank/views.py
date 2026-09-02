# -*- coding: utf-8 -*-
"""bank 模块字段元数据与视图配置（项目书 6.8 / 7.8）。"""

RECONCILE_STATE_OPTIONS = [
    {"value": "unreconciled", "label": "未对账"},
    {"value": "reconciled", "label": "已对账"},
]

FIELD_META = {
    "bank_statement": {
        "bank_alias": {"label": "银行", "type": "char"},
        "account_no": {"label": "银行账号", "type": "char"},
        "period": {"label": "所属期间", "type": "char", "readonly": True},
        "imported_at": {"label": "导入时间", "type": "datetime", "readonly": True},
        "line_count": {"label": "流水行数", "type": "integer", "readonly": True},
        "total_debit": {"label": "收入合计", "type": "decimal", "readonly": True},
        "total_credit": {"label": "支出合计", "type": "decimal", "readonly": True},
    },
    "bank_statement_line": {
        "statement_id": {"label": "所属批次", "type": "many2one", "relation": "bank_statement"},
        "trade_date": {"label": "交易日期", "type": "date", "required": True},
        "trade_no": {"label": "流水号", "type": "char"},
        "counterpart_name": {"label": "对方户名", "type": "char"},
        "summary": {"label": "交易摘要", "type": "char"},
        "debit": {"label": "收入金额", "type": "decimal",
                  "help": "钱进账（银行对账单的贷方发生额）"},
        "credit": {"label": "支出金额", "type": "decimal", "help": "钱出账"},
        "balance": {"label": "交易后余额", "type": "decimal", "readonly": True},
        "state": {"label": "对账状态", "type": "selection", "options": RECONCILE_STATE_OPTIONS,
                  "readonly": True},
        "move_id": {"label": "生成凭证", "type": "many2one", "relation": "account_move",
                    "readonly": True},
    },
}

VIEWS = {
    "bank_statement": {
        "label": "银行对账单",
        "list": {
            "fields": ["period", "bank_alias", "account_no", "line_count",
                       "total_debit", "total_credit", "imported_at"],
            "searchable": ["bank_alias", "account_no", "period"],
            "default_order": "period desc, id desc",
        },
        "form": {"groups": [{"label": "批次信息", "fields": ["period", "bank_alias", "account_no",
                                                            "line_count", "total_debit",
                                                            "total_credit", "imported_at"]}]},
    },
    "bank_statement_line": {
        "label": "银行流水",
        "list": {
            "fields": ["trade_date", "summary", "counterpart_name", "debit", "credit",
                       "balance", "state", "move_id"],
            "searchable": ["summary", "counterpart_name", "trade_no"],
            "default_order": "state asc, trade_date desc, id desc",
        },
        "form": {"groups": [{"label": "流水信息", "fields": ["trade_date", "trade_no",
                                                             "counterpart_name", "summary",
                                                             "debit", "credit", "balance"]},
                            {"label": "对账", "fields": ["state", "move_id"]}]},
    },
}
