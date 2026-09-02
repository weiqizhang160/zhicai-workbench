# -*- coding: utf-8 -*-
"""invoice 模块字段元数据与视图配置（项目书 6.7 / 7.6）。"""

DIRECTION_OPTIONS = [
    {"value": "output", "label": "销项（开出）"},
    {"value": "input", "label": "进项（收到）"},
]

INVOICE_TYPE_OPTIONS = [
    {"value": "special", "label": "增值税专用发票"},
    {"value": "normal", "label": "增值税普通发票"},
    {"value": "electronic", "label": "数电票"},
    {"value": "other", "label": "其他"},
]

INVOICE_STATE_OPTIONS = [
    {"value": "registered", "label": "已登记"},
    {"value": "entry_generated", "label": "已生成凭证"},
    {"value": "voided", "label": "已作废"},
]

# 费用类别（发票 category）：驱动进项发票 → 费用科目的自动记账映射
CATEGORY_OPTIONS = [
    {"value": "office", "label": "办公费"},
    {"value": "travel", "label": "差旅费"},
    {"value": "rent", "label": "房租"},
    {"value": "material", "label": "材料采购"},
    {"value": "entertain", "label": "业务招待费"},
    {"value": "utility", "label": "水电物业"},
    {"value": "telecom", "label": "通讯网络"},
    {"value": "logistics", "label": "运输物流"},
    {"value": "salary", "label": "工资社保"},
    {"value": "other", "label": "其他"},
]

# 税率快捷选项
TAX_RATE_OPTIONS = [
    {"value": "0.13", "label": "13%"},
    {"value": "0.09", "label": "9%"},
    {"value": "0.06", "label": "6%"},
    {"value": "0.05", "label": "5%"},
    {"value": "0.03", "label": "3%"},
    {"value": "0.01", "label": "1%"},
    {"value": "0.00", "label": "0%"},
]

FIELD_META = {
    "invoice_bill": {
        "direction": {"label": "方向", "type": "selection", "options": DIRECTION_OPTIONS,
                      "required": True},
        "invoice_type": {"label": "票种", "type": "selection", "options": INVOICE_TYPE_OPTIONS},
        "invoice_code": {"label": "发票代码", "type": "char"},
        "invoice_no": {"label": "发票号码", "type": "char", "required": True},
        "invoice_date": {"label": "开票日期", "type": "date", "required": True},
        "period": {"label": "所属期间", "type": "char", "readonly": True},
        "partner_name": {"label": "对方单位名称", "type": "char"},
        "partner_tax_no": {"label": "对方税号", "type": "char"},
        "partner_id": {"label": "关联往来单位", "type": "many2one", "relation": "res_partner"},
        "goods_amount": {"label": "不含税金额", "type": "decimal", "required": True},
        "tax_amount": {"label": "税额", "type": "decimal"},
        "total_amount": {"label": "价税合计", "type": "decimal", "readonly": True,
                         "help": "自动计算 = 不含税金额 + 税额"},
        "tax_rate": {"label": "税率", "type": "selection", "options": TAX_RATE_OPTIONS,
                     "help": "如 0.13 表示 13%"},
        "category": {"label": "费用类别", "type": "selection", "options": CATEGORY_OPTIONS,
                     "help": "进项发票用于自动记账的科目映射"},
        "state": {"label": "状态", "type": "selection", "options": INVOICE_STATE_OPTIONS,
                  "readonly": True},
        "move_id": {"label": "生成凭证", "type": "many2one", "relation": "account_move",
                    "readonly": True},
        "source": {"label": "来源", "type": "selection", "options": [
            {"value": "manual", "label": "手工录入"},
            {"value": "excel", "label": "Excel 导入"},
            {"value": "xml", "label": "数电票 XML"}], "readonly": True},
        "remark": {"label": "备注", "type": "text"},
        "attachment_path": {"label": "影像文件", "type": "char", "readonly": True},
    },
}

VIEWS = {
    "invoice_bill": {
        "label": "发票管理",
        "list": {
            "fields": ["invoice_date", "direction", "invoice_no", "partner_name",
                       "goods_amount", "tax_amount", "total_amount", "tax_rate",
                       "category", "state", "move_id"],
            "searchable": ["invoice_no", "partner_name", "invoice_code"],
            "default_order": "invoice_date desc, id desc",
        },
        "form": {
            "groups": [
                {"label": "票面信息", "fields": ["direction", "invoice_type", "invoice_code",
                                                  "invoice_no", "invoice_date", "period"]},
                {"label": "对方单位", "fields": ["partner_name", "partner_tax_no", "partner_id"]},
                {"label": "金额（价税合计自动计算）", "fields": ["goods_amount", "tax_rate",
                                                       "tax_amount", "total_amount"]},
                {"label": "记账", "fields": ["category", "state", "move_id"]},
                {"label": "其他", "fields": ["source", "attachment_path", "remark"]},
            ],
        },
    },
}
