# -*- coding: utf-8 -*-
"""contract 模块字段元数据与视图配置（项目书 6.13 / 7.4）。"""

FEE_TYPE_OPTIONS = [
    {"value": "monthly", "label": "按月"},
    {"value": "quarterly", "label": "按季"},
    {"value": "annual", "label": "按年"},
]

AGREEMENT_STATE_OPTIONS = [
    {"value": "active", "label": "履行中"},
    {"value": "expired", "label": "已到期"},
    {"value": "terminated", "label": "已终止"},
]

SERVICE_SCOPE_OPTIONS = [
    {"value": "bookkeeping", "label": "代理记账"},
    {"value": "tax_return", "label": "纳税申报"},
    {"value": "annual_inspection", "label": "工商年检"},
    {"value": "export_refund", "label": "出口退税"},
    {"value": "payroll", "label": "工资代发"},
    {"value": "other", "label": "其他"},
]

FEE_STATE_OPTIONS = [
    {"value": "unpaid", "label": "未收款"},
    {"value": "invoiced", "label": "已开票"},
    {"value": "paid", "label": "已收款"},
    {"value": "overdue", "label": "已逾期"},
]

FIELD_META = {
    "contract_agreement": {
        "book_id": {"label": "客户账套", "type": "many2one", "relation": "res_book",
                    "required": True},
        "contract_no": {"label": "合同编号", "type": "char", "readonly": True},
        "sign_date": {"label": "签订日期", "type": "date"},
        "start_date": {"label": "服务开始", "type": "date", "required": True},
        "end_date": {"label": "服务结束", "type": "date", "required": True},
        "service_scope": {"label": "服务范围", "type": "multiselect",
                          "options": SERVICE_SCOPE_OPTIONS,
                          "help": "多选：记账/报税/工商年检/出口退税…"},
        "fee_type": {"label": "收费周期", "type": "selection", "options": FEE_TYPE_OPTIONS},
        "fee_amount": {"label": "每期金额", "type": "decimal", "required": True},
        "payer_name": {"label": "付款方", "type": "char"},
        "state": {"label": "状态", "type": "selection", "options": AGREEMENT_STATE_OPTIONS},
        "remark": {"label": "备注", "type": "text"},
    },
    "contract_fee_item": {
        "agreement_id": {"label": "所属合同", "type": "many2one",
                         "relation": "contract_agreement", "readonly": True},
        "book_id": {"label": "客户账套", "type": "many2one", "relation": "res_book",
                    "readonly": True},
        "period": {"label": "收费期", "type": "char"},
        "amount": {"label": "应收金额", "type": "decimal"},
        "due_date": {"label": "到期日", "type": "date"},
        "state": {"label": "状态", "type": "selection", "options": FEE_STATE_OPTIONS},
        "paid_date": {"label": "收款日期", "type": "date"},
        "paid_amount": {"label": "实收金额", "type": "decimal"},
        "invoice_no": {"label": "发票号码", "type": "char"},
    },
}

VIEWS = {
    "contract_agreement": {
        "label": "代账合同",
        "list": {
            "fields": ["contract_no", "book_id", "start_date", "end_date",
                       "fee_type", "fee_amount", "state"],
            "searchable": ["contract_no"],
            "default_order": "id desc",
        },
        "form": {"groups": [
            {"label": "合同要素", "fields": ["book_id", "contract_no", "payer_name",
                                             "sign_date", "start_date", "end_date", "state"]},
            {"label": "收费设置", "fields": ["fee_type", "fee_amount", "service_scope"]},
            {"label": "备注", "fields": ["remark"]},
        ]},
    },
    "contract_fee_item": {
        "label": "收费计划",
        "cross_book": True,   # 总览模式下可跨账套看收费（收款登记/仪表盘穿透）
        "list": {
            "fields": ["period", "book_id", "agreement_id", "amount", "due_date",
                       "state", "paid_amount", "paid_date"],
            "searchable": ["period"],
            "default_order": "due_date, id",
        },
        "form": {"groups": [
            {"label": "收费信息", "fields": ["agreement_id", "book_id", "period", "amount",
                                             "due_date", "state"]},
            {"label": "收款", "fields": ["paid_date", "paid_amount", "invoice_no"]},
        ]},
    },
}
