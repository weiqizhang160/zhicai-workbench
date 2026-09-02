# -*- coding: utf-8 -*-
"""res_partner 模块字段元数据与视图配置。"""

TAXPAYER_OPTIONS = [
    {"value": "general", "label": "一般纳税人"},
    {"value": "small", "label": "小规模纳税人"},
]

FIELD_META = {
    "res_book": {
        "code": {"label": "账套编号", "type": "char", "readonly": True},
        "name": {"label": "公司全称", "type": "char", "required": True},
        "short_name": {"label": "简称", "type": "char", "required": True},
        "credit_no": {"label": "统一社会信用代码", "type": "char"},
        "taxpayer_type": {"label": "纳税人类型", "type": "selection", "options": TAXPAYER_OPTIONS,
                          "required": True},
        "is_foreign_trade": {"label": "外贸客户", "type": "boolean"},
        "industry": {"label": "行业", "type": "char"},
        "legal_person": {"label": "法定代表人", "type": "char"},
        "phone": {"label": "联系电话", "type": "char"},
        "address": {"label": "注册地址", "type": "char"},
        "accounting_standard": {"label": "会计准则", "type": "selection", "options": [
            {"value": "small", "label": "小企业会计准则"},
            {"value": "enterprise", "label": "企业会计准则"}]},
        "vat_period": {"label": "增值税申报周期", "type": "selection", "options": [
            {"value": "monthly", "label": "按月"},
            {"value": "quarterly", "label": "按季"}]},
        "bookkeeping_start": {"label": "接账起始月份", "type": "date"},
        "bank_accounts": {"label": "开户行账户", "type": "text", "help": "JSON：[{bank, account_no, alias}]"},
        "charge_status": {"label": "服务状态", "type": "selection", "options": [
            {"value": "normal", "label": "服务中"},
            {"value": "paused", "label": "暂停"},
            {"value": "terminated", "label": "已终止"}]},
        "remark": {"label": "备注", "type": "text"},
    },
    "res_partner": {
        "name": {"label": "单位名称", "type": "char", "required": True},
        "partner_type": {"label": "类型", "type": "selection", "options": [
            {"value": "customer", "label": "客户"},
            {"value": "supplier", "label": "供应商"},
            {"value": "both", "label": "客户/供应商"}], "required": True},
        "tax_no": {"label": "税号", "type": "char"},
        "is_company": {"label": "是否单位", "type": "boolean"},
        "phone": {"label": "电话", "type": "char"},
        "address": {"label": "地址", "type": "char"},
        "bank_account": {"label": "银行账号", "type": "char"},
        "remark": {"label": "备注", "type": "text"},
        "book_id": {"label": "所属账套", "type": "many2one", "relation": "res_book", "required": True},
    },
}

VIEWS = {
    "res_book": {
        "label": "客户管理",
        "cross_book": True,  # 客户列表本身跨账套（总览）
        "list": {
            "fields": ["code", "short_name", "taxpayer_type", "charge_status",
                       "is_foreign_trade", "accounting_standard"],
            "searchable": ["code", "short_name", "name", "credit_no"],
            "default_order": "code asc",
            "filters": [
                {"label": "服务中", "domain": [["charge_status", "=", "normal"]]},
                {"label": "一般纳税人", "domain": [["taxpayer_type", "=", "general"]]},
                {"label": "小规模", "domain": [["taxpayer_type", "=", "small"]]},
                {"label": "外贸客户", "domain": [["is_foreign_trade", "=", True]]},
                {"label": "已终止", "domain": [["charge_status", "=", "terminated"]]},
            ],
        },
        "form": {
            "groups": [
                {"label": "基本信息", "fields": ["code", "name", "short_name", "credit_no", "industry",
                                                  "legal_person", "phone", "address"]},
                {"label": "税务与核算", "fields": ["taxpayer_type", "is_foreign_trade",
                                                    "accounting_standard", "vat_period",
                                                    "bookkeeping_start"]},
                {"label": "服务管理", "fields": ["charge_status", "bank_accounts", "remark"]},
            ],
        },
    },
    "res_partner": {
        "label": "往来单位",
        "list": {
            "fields": ["name", "partner_type", "tax_no", "phone"],
            "searchable": ["name", "tax_no"],
            "default_order": "name asc",
            "filters": [
                {"label": "客户", "domain": [["partner_type", "=", "customer"]]},
                {"label": "供应商", "domain": [["partner_type", "=", "supplier"]]},
            ],
        },
        "form": {
            "groups": [
                {"label": "单位信息", "fields": ["name", "partner_type", "tax_no", "is_company",
                                                  "phone", "address", "bank_account", "remark"]},
            ],
        },
    },
}
