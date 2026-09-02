# -*- coding: utf-8 -*-
"""foreign_trade 模块：外贸专区（项目书 6.11 / 7.10）。

三本台账 + 平台链接中心：
- 报关单（ft_customs_decl + 商品行 ft_customs_line）；
- 收汇/结汇（ft_fx_receipt，关联报关单，一笔报关可多次收汇）；
- 出口退税（ft_export_refund，状态流转）。

菜单仅当至少一个账套 is_foreign_trade=true 时显示（7.10 DoD）。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class FtCustomsDecl(Base, BaseModelMixin):
    """报关单台账（对标 Odoo 无对应，外贸自建）。"""
    __tablename__ = "ft_customs_decl"
    _rec_name = "decl_no"
    _book_scoped = True

    decl_no: Mapped[str] = mapped_column(String(30), nullable=False, index=True,
                                         comment="报关单号（18 位）")
    export_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="出口日期")
    trade_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="FOB",
                                            comment="成交方式：FOB/CIF/CFR")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD",
                                          comment="币种")
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=1,
                                             comment="汇率（对人民币）")
    usd_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                comment="外币金额")
    cny_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                               comment="人民币总额")
    customer_abroad: Mapped[str | None] = mapped_column(String(200), nullable=True,
                                                        comment="境外客户")
    goods_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="件数")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套")

    @property
    def display_name(self) -> str:
        return self.decl_no


class FtCustomsLine(Base, BaseModelMixin):
    """报关单商品行。随报关单走（book_id 冗余便于过滤），不走通用 CRUD 的账套自动过滤。"""
    __tablename__ = "ft_customs_line"
    _rec_name = "goods_name"
    _book_scoped = False

    decl_id: Mapped[int] = mapped_column(ForeignKey("ft_customs_decl.id"), nullable=False,
                                         index=True, comment="所属报关单")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套（冗余）")
    hs_code: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="海关商品编码")
    goods_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="品名")
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0, comment="数量")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="单位")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0,
                                                comment="单价（外币）")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                            comment="金额（外币）")
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="备注")


class FxFxReceipt(Base, BaseModelMixin):
    """收汇/结汇台账。decl_id 可空（预收款等无报关单的收汇）。"""
    __tablename__ = "ft_fx_receipt"
    _rec_name = "display_name"
    _book_scoped = True

    decl_id: Mapped[int | None] = mapped_column(ForeignKey("ft_customs_decl.id"), nullable=True,
                                                index=True, comment="关联报关单（可空）")
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="收汇日期")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD", comment="币种")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                            comment="外币金额")
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=1,
                                             comment="汇率")
    cny_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                comment="人民币金额")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="receipt", index=True,
                                      comment="类型：receipt 收汇 / verification 待核查 / settlement 结汇")
    bank_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                              comment="银行手续费（人民币）")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套")

    @property
    def display_name(self) -> str:
        return f"{self.receipt_date.isoformat()} {self.currency} {self.amount}"


class FtExportRefund(Base, BaseModelMixin):
    """出口退税台账。"""
    __tablename__ = "ft_export_refund"
    _rec_name = "display_name"
    _book_scoped = True

    decl_id: Mapped[int] = mapped_column(ForeignKey("ft_customs_decl.id"), nullable=False,
                                         index=True, comment="关联报关单")
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True,
                                        comment="属期 YYYY-MM")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="免抵退",
                                      comment="退税方式：免抵退 / 免退")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="collecting",
                                        index=True,
                                        comment="状态：collecting/submitted/approved/received")
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                   comment="应退税额")
    received_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="到账日期")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套")

    @property
    def display_name(self) -> str:
        return f"{self.period} {self.kind} {self.refund_amount}"
