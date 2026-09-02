# -*- coding: utf-8 -*-
"""base 模块字段元数据与视图配置（模型驱动 UI 的配置源）。"""

FIELD_META = {
    "res_users": {
        "login": {"label": "登录账号", "type": "char", "required": True},
        "name": {"label": "姓名", "type": "char", "required": True},
        "role_id": {"label": "角色", "type": "many2one", "relation": "res_role", "required": False},
        "last_login_at": {"label": "最后登录", "type": "datetime", "readonly": True},
    },
    "res_role": {
        "code": {"label": "角色代码", "type": "selection", "required": True,
                 "options": [
                     {"value": "admin", "label": "管理员"},
                     {"value": "accountant", "label": "会计"},
                     {"value": "viewer", "label": "只读"},
                 ]},
        "name": {"label": "角色名称", "type": "char", "required": True},
        "permissions": {"label": "权限说明", "type": "text", "readonly": True},
    },
    "ir_config": {
        "key": {"label": "参数键", "type": "char", "required": True},
        "value": {"label": "参数值", "type": "text"},
        "remark": {"label": "说明", "type": "char"},
    },
    "audit_log": {
        "model": {"label": "模型", "type": "char", "readonly": True},
        "record_id": {"label": "记录ID", "type": "integer", "readonly": True},
        "user_id": {"label": "操作人", "type": "integer", "readonly": True},
        "action": {"label": "动作", "type": "char", "readonly": True},
        "changes": {"label": "变更明细", "type": "text", "readonly": True},
        "created_at": {"label": "时间", "type": "datetime", "readonly": True},
    },
}

VIEWS = {
    "res_users": {
        "label": "用户管理",
        "list": {
            "fields": ["login", "name", "role_id", "last_login_at"],
            "searchable": ["login", "name"],
        },
        "form": {
            "groups": [
                {"label": "基本信息", "fields": ["login", "name", "role_id", "last_login_at"]},
            ],
        },
    },
    "res_role": {
        "label": "角色",
        "list": {"fields": ["code", "name"], "searchable": ["code", "name"]},
        "form": {"groups": [{"label": "基本信息", "fields": ["code", "name"]}]},
    },
    "ir_config": {
        "label": "参数配置",
        "list": {"fields": ["key", "value", "remark"], "searchable": ["key", "remark"]},
        "form": {"groups": [{"label": "参数", "fields": ["key", "value", "remark"]}]},
    },
    "audit_log": {
        "label": "审计日志",
        "cross_book": True,
        "list": {
            "fields": ["created_at", "model", "record_id", "user_id", "action", "changes"],
            "searchable": ["model", "action"],
        },
    },
}
