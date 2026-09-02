# -*- coding: utf-8 -*-
"""contract 模块注册（M5）：代账合同与收费（项目书 6.13 / 7.4）。"""
from ...core.registry import ModuleDescriptor
from .models import ContractAgreement, ContractFeeItem
from .views import FIELD_META, VIEWS


def register() -> ModuleDescriptor:
    return ModuleDescriptor(
        name="contract",
        label="合同与收费",
        depends=["base", "res_partner"],
        menu=[
            {"key": "contracts", "label": "合同与收费", "route": "#/contracts",
             "icon": "Document", "group": "客户与合同"},
            {"key": "fee_items", "label": "收费计划", "table": "contract_fee_item",
             "icon": "Money", "group": "客户与合同"},
        ],
        models={
            "contract_agreement": ContractAgreement,
            "contract_fee_item": ContractFeeItem,
        },
        field_meta=FIELD_META,
        views=VIEWS,
        seed_fn=None,
    )
