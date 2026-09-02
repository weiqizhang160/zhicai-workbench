# -*- coding: utf-8 -*-
"""tax_decl 模块字段元数据与视图配置（项目书 6.10 / 7.9）。"""

TAX_KIND_OPTIONS = [
    {"value": "vat", "label": "增值税"},
    {"value": "surtax", "label": "附加税（城建/教育附加）"},
    {"value": "cit_quarterly", "label": "企业所得税（季度预缴）"},
    {"value": "cit_annual", "label": "企业所得税（年度汇算）"},
    {"value": "iit", "label": "个人所得税（工资薪金）"},
    {"value": "stamp", "label": "印花税（买卖合同）"},
]

# 项目书 7.9 颜色规范：pending 灰 / preparing 蓝 / submitted 橙 / paid 绿 / exempt 白 / 逾期红
DECL_STATE_OPTIONS = [
    {"value": "pending", "label": "待申报"},
    {"value": "preparing", "label": "准备中"},
    {"value": "submitted", "label": "已申报"},
    {"value": "paid", "label": "已缴款"},
    {"value": "done", "label": "已完成"},
    {"value": "exempt", "label": "免税/零申报"},
]

PERIOD_TYPE_OPTIONS = [
    {"value": "monthly", "label": "按月"},
    {"value": "quarterly", "label": "按季"},
    {"value": "yearly", "label": "按年"},
]

DEADLINE_RULE_OPTIONS = [
    {"value": "next_month_15", "label": "次月 15 日"},
    {"value": "quarter_next_month_15", "label": "次季首月 15 日"},
    {"value": "annual_0531", "label": "次年 5 月 31 日"},
]

FIELD_META = {
    "tax_calendar_rule": {
        "name": {"label": "规则名称", "type": "char", "required": True},
        "tax_kind": {"label": "税种", "type": "selection", "options": TAX_KIND_OPTIONS,
                     "required": True},
        "period_type": {"label": "申报频率", "type": "selection", "options": PERIOD_TYPE_OPTIONS},
        "deadline_rule": {"label": "截止日规则", "type": "selection",
                          "options": DEADLINE_RULE_OPTIONS},
        "applies_to": {"label": "适用账套条件", "type": "text",
                       "help": "JSON，如 {\"taxpayer_type\":\"small\"}；留空表示适用全部账套"},
        "enabled": {"label": "启用", "type": "boolean"},
        "is_seed": {"label": "内置规则", "type": "boolean", "readonly": True},
    },
    "tax_decl_item": {
        "book_id": {"label": "客户账套", "type": "many2one", "relation": "res_book",
                    "readonly": True},
        "tax_kind": {"label": "税种", "type": "selection", "options": TAX_KIND_OPTIONS},
        "period": {"label": "属期", "type": "char"},
        "due_date": {"label": "截止日", "type": "date"},
        "state": {"label": "状态", "type": "selection", "options": DECL_STATE_OPTIONS},
        "computed_amount": {"label": "系统计算应纳额", "type": "decimal", "readonly": True},
        "declared_amount": {"label": "实缴额", "type": "decimal"},
        "paid_date": {"label": "缴款日期", "type": "date"},
        "calc_snapshot": {"label": "计算底稿", "type": "text", "readonly": True},
        "remark": {"label": "备注", "type": "text"},
        "source": {"label": "来源", "type": "selection", "options": [
            {"value": "auto", "label": "规则生成"},
            {"value": "manual", "label": "手工补录"}], "readonly": True},
    },
}

VIEWS = {
    "tax_calendar_rule": {
        "label": "征期规则",
        "list": {
            "fields": ["name", "tax_kind", "period_type", "deadline_rule", "enabled"],
            "searchable": ["name"],
            "default_order": "tax_kind, id",
        },
        "form": {"groups": [
            {"label": "规则", "fields": ["name", "tax_kind", "period_type",
                                         "deadline_rule", "enabled"]},
            {"label": "适用范围", "fields": ["applies_to"]},
        ]},
    },
    "tax_decl_item": {
        "label": "申报台账",
        # 申报日历是「总览模式」页：要跨全部客户账套看申报期，
        # 因此在总览模式下放行跨账套查询（对标 Odoo record rules 白名单）
        "cross_book": True,
        "list": {
            "fields": ["period", "tax_kind", "due_date", "state",
                       "computed_amount", "declared_amount", "paid_date"],
            "searchable": ["period"],
            "default_order": "due_date, id",
        },
        "form": {"groups": [
            {"label": "申报信息", "fields": ["book_id", "tax_kind", "period", "due_date", "state"]},
            {"label": "金额", "fields": ["computed_amount", "declared_amount", "paid_date"]},
            {"label": "其他", "fields": ["source", "remark"]},
        ]},
    },
}
