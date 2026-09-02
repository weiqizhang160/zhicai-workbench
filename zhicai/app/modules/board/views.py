# -*- coding: utf-8 -*-
"""board 模块字段元数据与视图配置（项目书 6.13 / 7.2）。"""

CARD_KEY_OPTIONS = [
    {"value": "overview", "label": "本月概览"},
    {"value": "decl_alert", "label": "申报日历红牌"},
    {"value": "overdue", "label": "逾期预警"},
    {"value": "todo_tasks", "label": "待办任务"},
    {"value": "fee_month", "label": "收款月历"},
    {"value": "client_progress", "label": "各客户进度"},
]

FIELD_META = {
    "board_card": {
        "card_key": {"label": "卡片", "type": "selection", "options": CARD_KEY_OPTIONS,
                     "required": True},
        "position": {"label": "显示顺序", "type": "integer"},
        "config": {"label": "附加配置", "type": "text", "help": "JSON，如 {\"limit\": 10}"},
        "enabled": {"label": "启用", "type": "boolean"},
    },
}

VIEWS = {
    "board_card": {
        "label": "仪表盘卡片",
        "list": {
            "fields": ["card_key", "position", "enabled"],
            "searchable": ["card_key"],
            "default_order": "position, id",
        },
        "form": {"groups": [
            {"label": "卡片", "fields": ["card_key", "position", "enabled"]},
            {"label": "配置", "fields": ["config"]},
        ]},
    },
}
