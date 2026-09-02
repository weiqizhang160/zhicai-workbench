# -*- coding: utf-8 -*-
"""account 模块字段元数据与视图配置（M1：科目/账簿；M2：凭证/分录/期间锁/税率）。"""

ACCOUNT_TYPE_OPTIONS = [
    {"value": "asset_current", "label": "流动资产"},
    {"value": "asset_fixed", "label": "固定资产"},
    {"value": "asset_depreciation", "label": "折旧/摊销"},
    {"value": "liability_current", "label": "流动负债"},
    {"value": "liability_long", "label": "长期负债"},
    {"value": "equity", "label": "所有者权益"},
    {"value": "revenue", "label": "收入"},
    {"value": "cost", "label": "成本"},
    {"value": "expense", "label": "费用"},
    {"value": "other", "label": "其他"},
]

MOVE_STATE_OPTIONS = [
    {"value": "draft", "label": "草稿"},
    {"value": "posted", "label": "已过账"},
    {"value": "voided", "label": "已红冲"},
]

SOURCE_TYPE_OPTIONS = [
    {"value": "manual", "label": "手工录入"},
    {"value": "auto_invoice", "label": "发票自动生成"},
    {"value": "auto_bank", "label": "银行流水生成"},
    {"value": "auto_payroll", "label": "工资自动生成"},
    {"value": "closing", "label": "期末结转"},
    {"value": "reversal", "label": "红冲凭证"},
]

TAX_KIND_OPTIONS = [
    {"value": "vat_output", "label": "增值税销项"},
    {"value": "vat_input", "label": "增值税进项"},
    {"value": "surtax", "label": "附加税"},
    {"value": "stamp", "label": "印花税"},
    {"value": "cit", "label": "企业所得税"},
    {"value": "other", "label": "其他"},
]

FIELD_META = {
    "account_account": {
        "code": {"label": "科目编码", "type": "char", "required": True},
        "name": {"label": "科目名称", "type": "char", "required": True},
        "account_type": {"label": "科目类型", "type": "selection", "options": ACCOUNT_TYPE_OPTIONS},
        "direction": {"label": "余额方向", "type": "selection", "options": [
            {"value": "debit", "label": "借方"}, {"value": "credit", "label": "贷方"}]},
        "is_leaf": {"label": "末级科目", "type": "boolean"},
        "parent_id": {"label": "上级科目", "type": "many2one", "relation": "account_account"},
        "is_cash_flow": {"label": "现金流量科目", "type": "boolean"},
        "auxiliary_flags": {"label": "辅助核算", "type": "text"},
    },
    "account_journal": {
        "code": {"label": "凭证字", "type": "char", "required": True},
        "name": {"label": "名称", "type": "char", "required": True},
        "journal_type": {"label": "类型", "type": "selection", "options": [
            {"value": "general", "label": "记账凭证"},
            {"value": "receipt", "label": "收款凭证"},
            {"value": "payment", "label": "付款凭证"},
            {"value": "transfer", "label": "转账凭证"}]},
    },
    # ===== M2 =====
    "account_move": {
        "name": {"label": "凭证号", "type": "char", "readonly": True,
                 "help": "过账时自动生成，格式：记-202609-0001"},
        "journal_id": {"label": "凭证字", "type": "many2one", "relation": "account_journal", "required": True},
        "move_date": {"label": "凭证日期", "type": "date", "required": True},
        "period": {"label": "所属期间", "type": "char", "readonly": True, "help": "按凭证日期自动生成 YYYY-MM"},
        "state": {"label": "状态", "type": "selection", "options": MOVE_STATE_OPTIONS, "readonly": True},
        "source_type": {"label": "来源", "type": "selection", "options": SOURCE_TYPE_OPTIONS, "readonly": True},
        "attachment_count": {"label": "附件张数", "type": "integer"},
        "remark": {"label": "备查说明", "type": "text"},
        "reversed_move_id": {"label": "红冲凭证", "type": "many2one", "relation": "account_move", "readonly": True},
        "reversed_from_id": {"label": "红冲来源", "type": "many2one", "relation": "account_move", "readonly": True},
        "is_template": {"label": "常用模板", "type": "boolean"},
        "template_name": {"label": "模板名称", "type": "char"},
    },
    "account_move_line": {
        "move_id": {"label": "所属凭证", "type": "many2one", "relation": "account_move"},
        "line_no": {"label": "行号", "type": "integer"},
        "summary": {"label": "摘要", "type": "char", "required": True},
        "account_id": {"label": "科目", "type": "many2one", "relation": "account_account", "required": True},
        "partner_id": {"label": "往来单位", "type": "many2one", "relation": "res_partner"},
        "department": {"label": "部门", "type": "char"},
        "project": {"label": "项目", "type": "char"},
        "debit": {"label": "借方金额", "type": "decimal"},
        "credit": {"label": "贷方金额", "type": "decimal"},
    },
    "account_period_close": {
        "period": {"label": "期间", "type": "char", "required": True, "help": "格式 YYYY-MM"},
        "closed": {"label": "已结账", "type": "boolean"},
        "closed_at": {"label": "结账时间", "type": "datetime", "readonly": True},
        "note": {"label": "备注", "type": "text"},
    },
    "account_tax": {
        "name": {"label": "名称", "type": "char", "required": True},
        "tax_kind": {"label": "税种", "type": "selection", "options": TAX_KIND_OPTIONS},
        "rate": {"label": "税率", "type": "decimal", "required": True, "help": "小数形式，如 0.13 表示 13%"},
    },
}

VIEWS = {
    "account_account": {
        "label": "会计科目",
        "list": {
            "fields": ["code", "name", "account_type", "direction", "is_leaf"],
            "searchable": ["code", "name"],
            "default_order": "code asc",
        },
        "form": {
            "groups": [
                {"label": "科目信息", "fields": ["code", "name", "account_type", "direction",
                                                  "is_leaf", "parent_id", "is_cash_flow"]},
            ],
        },
    },
    "account_journal": {
        "label": "账簿（凭证字）",
        "list": {"fields": ["code", "name", "journal_type"], "searchable": ["code", "name"]},
        "form": {"groups": [{"label": "账簿信息", "fields": ["code", "name", "journal_type"]}]},
    },
    # ===== M2 =====
    "account_move": {
        "label": "记账凭证",
        "list": {
            "fields": ["name", "move_date", "period", "journal_id", "state", "source_type",
                       "attachment_count", "remark"],
            "searchable": ["name", "period"],
            "default_order": "period desc, move_date desc, id desc",
        },
        "form": {
            "groups": [
                {"label": "凭证信息", "fields": ["name", "journal_id", "move_date", "period",
                                                  "attachment_count", "remark"]},
                {"label": "状态与来源", "fields": ["state", "source_type", "reversed_move_id",
                                                    "reversed_from_id"]},
            ],
        },
    },
    "account_move_line": {
        "label": "凭证分录",
        "list": {"fields": ["move_id", "line_no", "summary", "account_id", "debit", "credit"],
                 "searchable": ["summary"]},
        "form": {"groups": [{"label": "分录", "fields": ["move_id", "line_no", "summary", "account_id",
                                                          "partner_id", "debit", "credit"]}]},
    },
    "account_period_close": {
        "label": "期末结账",
        "list": {"fields": ["period", "closed", "closed_at", "note"], "searchable": ["period"]},
        "form": {"groups": [{"label": "结账信息", "fields": ["period", "closed", "closed_at", "note"]}]},
    },
    "account_tax": {
        "label": "税率设置",
        "list": {"fields": ["name", "tax_kind", "rate"], "searchable": ["name"]},
        "form": {"groups": [{"label": "税率", "fields": ["name", "tax_kind", "rate"]}]},
    },
}
