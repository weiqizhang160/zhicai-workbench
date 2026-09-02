# -*- coding: utf-8 -*-
"""foreign_trade 模块注册（M6）：报关单 / 收汇 / 出口退税 + 平台链接中心。"""
from ...core.registry import ModuleDescriptor
from .models import FtCustomsDecl, FtCustomsLine, FtExportRefund, FxFxReceipt
from .service import ensure_platform_configs
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="foreign_trade",
        label="外贸专区",
        depends=["base", "res_partner"],
        menu=[
            # foreign_only=True：仅当至少一个账套 is_foreign_trade=true 时显示（7.10 DoD）
            {"key": "ft", "label": "外贸台账", "route": "#/foreign-trade",
             "icon": "Ship", "group": "外贸专区", "foreign_only": True},
        ],
        models={
            "ft_customs_decl": FtCustomsDecl,
            "ft_customs_line": FtCustomsLine,
            "ft_fx_receipt": FxFxReceipt,
            "ft_export_refund": FtExportRefund,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=ensure_platform_configs,
    )
