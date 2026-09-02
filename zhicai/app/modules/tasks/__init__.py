# -*- coding: utf-8 -*-
"""tasks 模块注册（M5）：任务与待办看板（项目书 6.13 / 7.4）。"""
from ...core.registry import ModuleDescriptor
from .models import TaskTask
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="tasks",
        label="任务",
        depends=["base", "res_partner"],
        menu=[
            {"key": "tasks_board", "label": "任务看板", "route": "#/tasks",
             "icon": "Odometer", "group": "任务与文档"},
            {"key": "task_list", "label": "任务列表", "table": "task_task",
             "icon": "List", "group": "任务与文档"},
        ],
        models={
            "task_task": TaskTask,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=None,
    )
