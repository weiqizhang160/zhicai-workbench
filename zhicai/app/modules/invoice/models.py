# -*- coding: utf-8 -*-
"""invoice 模块：发票登记（项目书 6.7）。

一张表管进项 + 销项（对标 Odoo 用 move_type 区分发票形态的做法）。
价税合计 total_amount = goods_amount + tax_amount，由 service 层用 Decimal 计算（禁 float）。
"""
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class InvoiceBill(Base, BaseModelMixin):
    """进项/销项发票登记（对标 Odoo account.move 的发票形态）。"""
    __tablename__ = "invoice_bill"
    _rec_name = "display_name"
    _book_scoped = True

    direction: Mapped[str] = mapped_column(String(10), nullable=False, index=True,
                                           comment="方向：input 进项 / output 销项")
    invoice_type: Mapped[str] = mapped_column(String(20), nullable=False, default="special",
                                              comment="票种：special 专票 / normal 普票 / electronic 数电票 / other")
    invoice_code: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="发票代码")
    invoice_no: Mapped[str] = mapped_column(String(30), nullable=False, index=True, comment="发票号码")
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="开票日期")
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True,
                                        comment="所属期间 YYYY-MM（冗余，报表按此过滤）")

    # 往来单位：快照式存储（发票上的名称/税号），可选关联到账套内的往来单位
    partner_name: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="开票方/受票方名称")
    partner_tax_no: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="对方税号")
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("res_partner.id"), nullable=True,
                                                   comment="可选关联往来单位")

    goods_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                comment="不含税金额")
    tax_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0, comment="税额")
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                comment="价税合计（= 不含税 + 税额）")
    tax_rate: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, default=0,
                                            comment="税率，如 0.13")

    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True,
                                                 comment="费用类别（办公/差旅/房租/材料…），用于自动记账科目映射")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="registered", index=True,
                                       comment="状态：registered / entry_generated / voided")
    move_id: Mapped[int | None] = mapped_column(ForeignKey("account_move.id"), nullable=True,
                                                comment="自动记账生成的凭证（可追溯）")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True,
                                                        comment="发票影像相对路径（M6 文档中心将升级为正式关联）")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual",
                                        comment="来源：manual 手工 / excel 导入 / xml 数电票")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套")

    @property
    def display_name(self) -> str:
        return f"{self.invoice_no}（{self.partner_name or '—'}）"

    @property
    def can_generate_entry(self) -> bool:
        """只有已登记且未作废的发票才能生成凭证（幂等基础）。"""
        return self.state == "registered"
