# -*- coding: utf-8 -*-
"""maintenance 模块字段元数据与视图配置（项目书 7.13 / 7.14）。

设置页（M7-2）是自定义 Vue 视图；这里的 FIELD_META/VIEWS 让备份日志、
计划任务也能通过通用 CRUD 浏览（只读为主，daily_time/active 可改）。
"""

CRON_STATUS_OPTIONS = [
    {"value": "ok", "label": "成功"},
    {"value": "fail", "label": "失败"},
]

FIELD_META = {
    "ir_cron": {
        "code": {"label": "任务代码", "type": "char", "readonly": True},
        "name": {"label": "任务名称", "type": "char", "readonly": True},
        "active": {"label": "启用", "type": "boolean"},
        "daily_time": {"label": "每日时刻", "type": "char", "help": "HH:MM，如 07:30"},
        "last_run_date": {"label": "最后执行日", "type": "date", "readonly": True},
        "last_status": {"label": "最近结果", "type": "selection", "options": CRON_STATUS_OPTIONS,
                        "readonly": True},
        "remark": {"label": "说明", "type": "char", "readonly": True},
    },
    "backup_log": {
        "file_name": {"label": "备份文件", "type": "char", "readonly": True},
        "file_size": {"label": "大小(字节)", "type": "integer", "readonly": True},
        "duration_ms": {"label": "耗时(毫秒)", "type": "integer", "readonly": True},
        "integrity": {"label": "完整性", "type": "char", "readonly": True},
        "status": {"label": "结果", "type": "char", "readonly": True},
        "trigger": {"label": "触发方式", "type": "char", "readonly": True},
        "message": {"label": "说明", "type": "text", "readonly": True},
        "created_at": {"label": "备份时间", "type": "datetime", "readonly": True},
    },
    "ir_cron_run": {
        "job_code": {"label": "任务代码", "type": "char", "readonly": True},
        "run_date": {"label": "执行日", "type": "date", "readonly": True},
        "status": {"label": "结果", "type": "char", "readonly": True},
        "trigger": {"label": "触发方式", "type": "char", "readonly": True},
        "message": {"label": "错误信息", "type": "text", "readonly": True},
    },
}

VIEWS = {
    "ir_cron": {
        "label": "计划任务",
        "cross_book": True,
        "list": {
            "fields": ["code", "name", "daily_time", "active", "last_run_date", "last_status"],
        },
        "form": {"groups": [
            {"label": "任务", "fields": ["code", "name", "daily_time", "active",
                                         "last_run_date", "last_status", "remark"]},
        ]},
    },
    "backup_log": {
        "label": "备份日志",
        "cross_book": True,
        "list": {
            "fields": ["created_at", "file_name", "file_size", "status", "trigger", "integrity"],
        },
        "form": {"groups": [
            {"label": "备份", "fields": ["created_at", "file_name", "file_size", "duration_ms",
                                         "integrity", "status", "trigger", "message"]},
        ]},
    },
    "ir_cron_run": {
        "label": "任务执行留痕",
        "cross_book": True,
        "list": {
            "fields": ["run_date", "job_code", "status", "trigger", "started_at", "finished_at"],
        },
        "form": {"groups": [
            {"label": "执行", "fields": ["job_code", "run_date", "status", "trigger",
                                         "started_at", "finished_at", "message"]},
        ]},
    },
}
