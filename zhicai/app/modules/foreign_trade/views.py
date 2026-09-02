# -*- coding: utf-8 -*-
"""foreign_trade 模块字段元数据与视图配置（项目书 6.11 / 7.10）。"""

TRADE_MODE_OPTIONS = [
    {"value": "FOB", "label": "FOB 离岸价"},
    {"value": "CIF", "label": "CIF 到岸价"},
    {"value": "CFR", "label": "CFR 成本加运费"},
]

FX_KIND_OPTIONS = [
    {"value": "receipt", "label": "收汇"},
    {"value": "verification", "label": "待核查"},
    {"value": "settlement", "label": "结汇"},
]

REFUND_STATUS_OPTIONS = [
    {"value": "collecting", "label": "资料收集中"},
    {"value": "submitted", "label": "已申报"},
    {"value": "approved", "label": "已审批"},
    {"value": "received", "label": "已到账"},
]

REFUND_KIND_OPTIONS = [
    {"value": "免抵退", "label": "免抵退"},
    {"value": "免退", "label": "免退"},
]

FIELD_META = {
    "ft_customs_decl": {
        "book_id": {"label": "所属客户", "type": "many2one", "relation": "res_book"},
        "decl_no": {"label": "报关单号", "type": "char", "required": True},
        "export_date": {"label": "出口日期", "type": "date", "required": True},
        "trade_mode": {"label": "成交方式", "type": "selection", "options": TRADE_MODE_OPTIONS},
        "currency": {"label": "币种", "type": "char"},
        "fx_rate": {"label": "汇率", "type": "decimal"},
        "usd_amount": {"label": "外币金额", "type": "decimal"},
        "cny_total": {"label": "人民币总额", "type": "decimal"},
        "customer_abroad": {"label": "境外客户", "type": "char"},
        "goods_count": {"label": "件数", "type": "integer"},
        "remark": {"label": "备注", "type": "text"},
    },
    "ft_fx_receipt": {
        "book_id": {"label": "所属客户", "type": "many2one", "relation": "res_book"},
        "decl_id": {"label": "报关单", "type": "many2one", "relation": "ft_customs_decl"},
        "receipt_date": {"label": "收汇日期", "type": "date", "required": True},
        "currency": {"label": "币种", "type": "char"},
        "amount": {"label": "外币金额", "type": "decimal"},
        "fx_rate": {"label": "汇率", "type": "decimal"},
        "cny_amount": {"label": "人民币金额", "type": "decimal"},
        "kind": {"label": "类型", "type": "selection", "options": FX_KIND_OPTIONS},
        "bank_fee": {"label": "银行手续费", "type": "decimal"},
        "remark": {"label": "备注", "type": "text"},
    },
    "ft_export_refund": {
        "book_id": {"label": "所属客户", "type": "many2one", "relation": "res_book"},
        "decl_id": {"label": "报关单", "type": "many2one", "relation": "ft_customs_decl"},
        "period": {"label": "属期", "type": "char", "required": True},
        "kind": {"label": "退税方式", "type": "selection", "options": REFUND_KIND_OPTIONS},
        "status": {"label": "状态", "type": "selection", "options": REFUND_STATUS_OPTIONS},
        "refund_amount": {"label": "应退税额", "type": "decimal"},
        "received_date": {"label": "到账日期", "type": "date"},
        "remark": {"label": "备注", "type": "text"},
    },
}

VIEWS = {
    "ft_customs_decl": {
        "label": "报关单",
        "list": {
            "fields": ["decl_no", "export_date", "trade_mode", "currency", "usd_amount",
                       "cny_total", "customer_abroad"],
            "searchable": ["decl_no", "customer_abroad"],
        },
        "form": {"groups": [
            {"label": "报关单", "fields": ["decl_no", "export_date", "trade_mode", "currency",
                                           "fx_rate", "usd_amount", "cny_total",
                                           "customer_abroad", "goods_count", "remark"]},
        ]},
    },
    "ft_fx_receipt": {
        "label": "收汇台账",
        "cross_book": True,
        "list": {
            "fields": ["receipt_date", "book_id", "decl_id", "currency", "amount", "cny_amount",
                       "kind"],
            "searchable": [],
        },
        "form": {"groups": [
            {"label": "收汇", "fields": ["receipt_date", "book_id", "decl_id", "currency",
                                         "amount", "fx_rate", "cny_amount", "kind",
                                         "bank_fee", "remark"]},
        ]},
    },
    "ft_export_refund": {
        "label": "出口退税",
        "cross_book": True,
        "list": {
            "fields": ["period", "book_id", "decl_id", "kind", "status", "refund_amount",
                       "received_date"],
            "searchable": [],
        },
        "form": {"groups": [
            {"label": "退税", "fields": ["period", "book_id", "decl_id", "kind", "status",
                                         "refund_amount", "received_date", "remark"]},
        ]},
    },
}
