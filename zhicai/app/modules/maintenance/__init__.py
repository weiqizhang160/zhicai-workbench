# -*- coding: utf-8 -*-
"""maintenance 模块注册（M7）：备份与计划任务（项目书 7.13）。

菜单「系统设置」在 M7-2 设置页完成后挂到 #/settings（避免空路由）。
"""
from ...core.registry import ModuleDescriptor
from .models import BackupLog, IrCron, IrCronRun
from .views import FIELD_META, VIEWS
from . import seed as seed_mod


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="maintenance",
        label="运维",
        depends=["base", "res_partner", "tax_decl", "contract", "tasks"],
        menu=[
            {"key": "settings", "label": "系统设置", "route": "#/settings",
             "icon": "Tools", "group": "系统"},
        ],
        models={
            "ir_cron": IrCron,
            "ir_cron_run": IrCronRun,
            "backup_log": BackupLog,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=seed_mod.seed,
    )
