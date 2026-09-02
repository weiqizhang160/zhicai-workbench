# -*- coding: utf-8 -*-
"""auto_entry 模块字段元数据与视图配置（项目书 6.9 / 7.7）。"""

TRIGGER_OPTIONS = [
    {"value": "invoice_output", "label": "销项发票"},
    {"value": "invoice_input", "label": "进项发票"},
    {"value": "bank_line", "label": "银行流水"},
    {"value": "payroll", "label": "工资批次"},
]

RESULT_OPTIONS = [
    {"value": "ok", "label": "成功"},
    {"value": "failed", "label": "失败"},
    {"value": "skipped", "label": "跳过（无匹配规则）"},
]

FIELD_META = {
    "auto_entry_rule": {
        "name": {"label": "规则名称", "type": "char", "required": True},
        "trigger": {"label": "触发源", "type": "selection", "options": TRIGGER_OPTIONS,
                    "required": True},
        "match_condition": {"label": "匹配条件", "type": "text",
                            "help": 'JSON，如 {"invoice_type":"special"} 或 {"summary_ilike":"工资"}'},
        "journal_code": {"label": "凭证字", "type": "char", "help": "生成凭证使用的凭证字，默认 记"},
        "line_template": {"label": "分录模板", "type": "text", "required": True,
                          "help": 'JSON 数组：[{side, account, summary, amount}]，'
                                  'amount 支持 {total_amount} 变量与 ={goods_amount}*0.13 表达式'},
        "priority": {"label": "优先级", "type": "integer", "help": "数字小者优先"},
        "enabled": {"label": "启用", "type": "boolean"},
        "is_seed": {"label": "内置规则", "type": "boolean", "readonly": True},
    },
    "auto_entry_log": {
        "rule_id": {"label": "命中规则", "type": "many2one", "relation": "auto_entry_rule"},
        "source_model": {"label": "源单据", "type": "char", "readonly": True},
        "source_id": {"label": "源单据 ID", "type": "integer", "readonly": True},
        "result": {"label": "结果", "type": "selection", "options": RESULT_OPTIONS, "readonly": True},
        "move_id": {"label": "生成凭证", "type": "many2one", "relation": "account_move",
                    "readonly": True},
        "message": {"label": "说明", "type": "text", "readonly": True},
        "created_at": {"label": "执行时间", "type": "datetime", "readonly": True},
    },
}

VIEWS = {
    "auto_entry_rule": {
        "label": "自动记账规则",
        "list": {
            "fields": ["priority", "name", "trigger", "journal_code", "enabled", "is_seed"],
            "searchable": ["name"],
            "default_order": "priority asc, id asc",
        },
        "form": {"groups": [
            {"label": "规则", "fields": ["name", "trigger", "priority", "enabled"]},
            {"label": "匹配与分录", "fields": ["match_condition", "journal_code", "line_template"]},
        ]},
    },
    "auto_entry_log": {
        "label": "自动记账日志",
        "list": {
            "fields": ["created_at", "source_model", "source_id", "rule_id", "result",
                       "move_id", "message"],
            "searchable": ["message"],
            "default_order": "id desc",
        },
        "form": {"groups": [{"label": "执行记录", "fields": ["created_at", "source_model",
                                                             "source_id", "rule_id", "result",
                                                             "move_id", "message"]}]},
    },
}
