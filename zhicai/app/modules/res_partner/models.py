# -*- coding: utf-8 -*-
"""res_partner 模块模型：客户账套 res_book（对标 Odoo res.company）+ 往来单位 res_partner。"""
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class ResBook(Base, BaseModelMixin):
    """客户账套：一家代理客户公司 = 一个账套（对标 Odoo res.company，项目书 6.3）。"""
    __tablename__ = "res_book"
    _rec_name = "short_name"
    _book_scoped = False  # 账套表本身跨账套可见（客户列表）

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment="账套编号")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="客户公司全称")
    short_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="简称")
    credit_no: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="统一社会信用代码")
    taxpayer_type: Mapped[str] = mapped_column(String(10), nullable=False, default="small",
                                               comment="纳税人类型：general/small")
    is_foreign_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="外贸客户")
    industry: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="行业")
    legal_person: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="法人")
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True, comment="电话")
    address: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="注册地址")
    accounting_standard: Mapped[str] = mapped_column(String(20), nullable=False, default="small",
                                                     comment="会计准则：small/enterprise")
    vat_period: Mapped[str] = mapped_column(String(10), nullable=False, default="quarterly",
                                            comment="增值税申报周期：monthly/quarterly")
    bookkeeping_start: Mapped[date | None] = mapped_column(Date, nullable=True, comment="接账起始月份")
    bank_accounts: Mapped[str | None] = mapped_column(Text, nullable=True, comment="开户行账户 JSON 列表")
    charge_status: Mapped[str] = mapped_column(String(15), nullable=False, default="normal",
                                               comment="服务状态：normal/paused/terminated")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class ResPartner(Base, BaseModelMixin):
    """往来单位（对标 Odoo res.partner，项目书 6.4）——账套下的客户/供应商。"""
    __tablename__ = "res_partner"
    _rec_name = "name"
    _book_scoped = True

    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="单位名称")
    partner_type: Mapped[str] = mapped_column(String(10), nullable=False, default="customer",
                                              comment="类型：customer/supplier/both")
    tax_no: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="税号")
    is_company: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否单位")
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True, comment="电话")
    address: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="地址")
    bank_account: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="银行账号")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False, index=True,
                                         comment="所属账套")
