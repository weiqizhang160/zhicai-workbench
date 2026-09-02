# -*- coding: utf-8 -*-
"""payroll 模块字段元数据与视图配置（项目书 6.12 / 7.11）。"""

BATCH_STATE_OPTIONS = [
    {"value": "draft", "label": "草稿"},
    {"value": "confirmed", "label": "已确认"},
    {"value": "paid", "label": "已发放"},
]

FIELD_META = {
    "payroll_batch": {
        "book_id": {"label": "所属客户", "type": "many2one", "relation": "res_book"},
        "period": {"label": "工资期间", "type": "char", "required": True,
                   "help": "YYYY-MM，每账套每期间一份批次"},
        "state": {"label": "状态", "type": "selection", "options": BATCH_STATE_OPTIONS},
        "employee_count": {"label": "员工人数", "type": "integer", "readonly": True},
        "total_gross": {"label": "应发合计", "type": "decimal", "readonly": True},
        "total_net": {"label": "实发合计", "type": "decimal", "readonly": True},
        "social_base": {"label": "社保基数汇总", "type": "decimal", "readonly": True},
        "accrual_move_id": {"label": "计提凭证", "type": "integer", "readonly": True},
        "payment_move_id": {"label": "发放凭证", "type": "integer", "readonly": True},
        "remark": {"label": "备注", "type": "text"},
    },
    "payroll_line": {
        "batch_id": {"label": "所属批次", "type": "many2one", "relation": "payroll_batch"},
        "employee_name": {"label": "员工姓名", "type": "char", "required": True},
        "id_card_tail": {"label": "证件后四位", "type": "char"},
        "gross_salary": {"label": "应发工资", "type": "decimal"},
        "social_employee": {"label": "个人社保", "type": "decimal"},
        "social_employer": {"label": "单位社保", "type": "decimal"},
        "fund_employer": {"label": "单位公积金", "type": "decimal"},
        "iit": {"label": "代扣个税", "type": "decimal"},
        "net_salary": {"label": "实发", "type": "decimal", "readonly": True},
        "remark": {"label": "备注", "type": "text"},
    },
}

VIEWS = {
    "payroll_batch": {
        "label": "工资批次",
        "cross_book": True,
        "list": {
            "fields": ["period", "book_id", "state", "employee_count", "total_gross",
                       "total_net"],
            "searchable": ["period"],
        },
        "form": {"groups": [
            {"label": "批次", "fields": ["period", "book_id", "state", "remark"]},
        ]},
    },
    "payroll_line": {
        "label": "员工工资行",
        "list": {
            "fields": ["employee_name", "gross_salary", "social_employee", "iit",
                       "net_salary"],
            "searchable": ["employee_name"],
        },
    },
}
