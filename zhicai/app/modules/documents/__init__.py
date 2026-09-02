# -*- coding: utf-8 -*-
"""documents 模块注册（M6）：文档中心（项目书 6.12 / 7.12）。"""
from ...core.registry import ModuleDescriptor
from .models import DocDocument
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="documents",
        label="文档中心",
        depends=["base", "res_partner"],
        menu=[
            {"key": "documents", "label": "文档中心", "route": "#/documents",
             "icon": "FolderOpened", "group": "任务与文档"},
        ],
        models={
            "doc_document": DocDocument,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=None,
    )
