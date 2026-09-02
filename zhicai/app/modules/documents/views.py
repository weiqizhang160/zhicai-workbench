# -*- coding: utf-8 -*-
"""documents 模块字段元数据与视图配置（项目书 6.12 / 7.12）。"""

DOC_TYPE_OPTIONS = [
    {"value": "license", "label": "营业执照"},
    {"value": "contract", "label": "合同"},
    {"value": "tax_receipt", "label": "申报回执"},
    {"value": "bank_slip", "label": "银行回单"},
    {"value": "customs", "label": "报关单"},
    {"value": "invoice", "label": "发票影像"},
    {"value": "payroll", "label": "工资表"},
    {"value": "other", "label": "其他"},
]

FIELD_META = {
    "doc_document": {
        "book_id": {"label": "所属客户", "type": "many2one", "relation": "res_book",
                    "required": True},
        "name": {"label": "文档名称", "type": "char", "required": True},
        "doc_type": {"label": "类型", "type": "selection", "options": DOC_TYPE_OPTIONS},
        "tags": {"label": "标签", "type": "char", "help": "多个标签用逗号分隔"},
        "doc_year": {"label": "年份", "type": "integer"},
        "attachment_path": {"label": "文件路径", "type": "char", "readonly": True},
        "file_size": {"label": "大小(字节)", "type": "integer", "readonly": True},
        "source_model": {"label": "来源模型", "type": "char", "readonly": True},
        "source_id": {"label": "来源单据ID", "type": "integer", "readonly": True},
        "remark": {"label": "备注", "type": "text"},
    },
}

VIEWS = {
    "doc_document": {
        "label": "文档中心",
        # 跨账套列表是核心场景（7.12 DoD）；通用 CRUD 仍可按账套用
        "cross_book": True,
        "list": {
            "fields": ["name", "book_id", "doc_type", "tags", "doc_year",
                       "source_model", "source_id"],
            "searchable": ["name", "tags"],
        },
        "form": {"groups": [
            {"label": "文档", "fields": ["name", "book_id", "doc_type", "tags", "doc_year",
                                         "attachment_path", "file_size", "remark"]},
        ]},
    },
}
