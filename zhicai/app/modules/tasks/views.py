# -*- coding: utf-8 -*-
"""tasks 模块字段元数据与视图配置（项目书 6.13 / 7.4）。"""

PRIORITY_OPTIONS = [
    {"value": "low", "label": "低"},
    {"value": "normal", "label": "普通"},
    {"value": "high", "label": "高"},
    {"value": "urgent", "label": "紧急"},
]

TASK_STATE_OPTIONS = [
    {"value": "todo", "label": "待办"},
    {"value": "doing", "label": "进行中"},
    {"value": "done", "label": "已完成"},
    {"value": "cancelled", "label": "已取消"},
]

FIELD_META = {
    "task_task": {
        "book_id": {"label": "所属客户", "type": "many2one", "relation": "res_book",
                    "help": "留空 = 全局任务（不属于任何客户）"},
        "title": {"label": "标题", "type": "char", "required": True},
        "description": {"label": "描述", "type": "text"},
        "due_date": {"label": "到期日", "type": "date"},
        "priority": {"label": "优先级", "type": "selection", "options": PRIORITY_OPTIONS},
        "state": {"label": "状态", "type": "selection", "options": TASK_STATE_OPTIONS},
        "assignee_id": {"label": "负责人", "type": "integer", "readonly": True,
                        "help": "预留字段"},
        "source_model": {"label": "来源模型", "type": "char", "readonly": True},
        "source_id": {"label": "来源记录", "type": "integer", "readonly": True},
        "reminder_sent": {"label": "已提醒", "type": "boolean", "readonly": True},
    },
}

VIEWS = {
    "task_task": {
        "label": "任务",
        "cross_book": True,   # 总览模式显示全局任务 + 全部客户任务
        "list": {
            "fields": ["title", "book_id", "due_date", "priority", "state"],
            "searchable": ["title"],
            "default_order": "due_date, priority, id",
        },
        "form": {"groups": [
            {"label": "任务", "fields": ["title", "book_id", "due_date", "priority", "state"]},
            {"label": "详情", "fields": ["description"]},
        ]},
    },
}
