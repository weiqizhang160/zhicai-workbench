# -*- coding: utf-8 -*-
"""base 模块注册（所有模块的依赖根）。"""
from ...core.registry import ModuleDescriptor
from .models import AuditLog, IrConfig, IrSequence, NoteMessage, ResRole, ResUsers
from .views import FIELD_META, VIEWS
from . import seed as seed_mod


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="base",
        label="系统",
        depends=[],
        menu=[
            {"key": "users", "label": "用户管理", "table": "res_users", "icon": "User", "group": "系统"},
            {"key": "roles", "label": "角色管理", "table": "res_role", "icon": "Avatar", "group": "系统"},
            {"key": "configs", "label": "参数配置", "table": "ir_config", "icon": "Setting", "group": "系统"},
            {"key": "audit", "label": "审计日志", "table": "audit_log", "icon": "Document", "group": "系统"},
        ],
        models={
            "res_role": ResRole,
            "res_users": ResUsers,
            "ir_config": IrConfig,
            "ir_sequence": IrSequence,
            "audit_log": AuditLog,
            "note_message": NoteMessage,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=seed_mod.seed,
    )
