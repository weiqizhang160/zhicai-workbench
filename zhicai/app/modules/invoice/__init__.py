# -*- coding: utf-8 -*-
"""invoice 模块注册（M3）：进项/销项发票登记。"""
from ...core.registry import ModuleDescriptor
from .models import InvoiceBill
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="invoice",
        label="票据",
        depends=["base", "res_partner", "account"],
        menu=[
            # 进项/销项在一个页面内 Tab 切换（项目书 7.6），故用定制页
            {"key": "invoices", "label": "发票管理", "route": "#/invoices",
             "icon": "Ticket", "group": "票据与银行"},
        ],
        models={"invoice_bill": InvoiceBill},
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=None,
    )
