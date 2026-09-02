# -*- coding: utf-8 -*-
"""documents 模块：文档中心（项目书 6.12 / 7.12）。

设计要点：
- 所有客户的营业执照 / 合同 / 申报回执 / 银行回单 / 报关单等文件集中一处；
- 跨账套列表（客户 / 类型 / 标签 / 年份筛选），也可以按当前账套过滤；
- 文件实体存 data/attachments/年/月/ 下，表里只存相对路径；
- source_model/source_id 把文档挂到业务单据（发票影像、报关单扫描件等），
  支持从文档中心反查来源单据（7.12 DoD）。
"""
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class DocDocument(Base, BaseModelMixin):
    """文档（对标 Odoo ir.attachment + 自建分类台账）。"""
    __tablename__ = "doc_document"
    _rec_name = "name"
    # 跨账套列表是本模块的核心场景，但单账套模式下仍按账套过滤，
    # 过滤逻辑在 documents_api 显式处理（参考 tasks 模块做法）
    _book_scoped = False

    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属客户账套")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="文档名称")
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False, default="other",
                                          index=True, comment="类型：license/contract/tax_receipt/"
                                                              "bank_slip/customs/invoice/payroll/other")
    tags: Mapped[str | None] = mapped_column(String(200), nullable=True,
                                             comment="标签（逗号分隔）")
    doc_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True,
                                                 comment="所属年份（筛选用）")
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True,
                                                        comment="文件相对路径（attachments/年/月/文件）")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
                                           comment="文件大小（字节）")
    source_model: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True,
                                                     comment="来源模型，如 invoice_bill / ft_customs_decl")
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True,
                                                  comment="来源记录 ID")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
