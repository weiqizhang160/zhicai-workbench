# -*- coding: utf-8 -*-
"""account 模块：科目/账簿/凭证/分录/期间锁/税率。

对标 Odoo account.account / account.journal / account.move / account.move.line。
M1：科目 + 账簿（骨架）；M2：凭证 + 分录 + 期间锁 + 税率（记账核心）。
"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class AccountAccount(Base, BaseModelMixin):
    """会计科目（对标 account.account，项目书 6.5）。"""
    __tablename__ = "account_account"
    _rec_name = "display_name"
    _book_scoped = True

    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment="科目编码")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="科目名称")
    account_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="科目类型")
    direction: Mapped[str] = mapped_column(String(6), nullable=False, default="debit", comment="余额方向：debit/credit")
    is_leaf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否末级科目")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("account_account.id"), nullable=True, comment="上级科目")
    is_cash_flow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="现金流量表科目")
    auxiliary_flags: Mapped[str | None] = mapped_column(Text, nullable=True, comment="辅助核算标志 JSON")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False, index=True,
                                         comment="所属账套")

    @property
    def display_name(self) -> str:
        return f"{self.code} {self.name}"


class AccountJournal(Base, BaseModelMixin):
    """账簿/凭证字（对标 account.journal，项目书 6.5）。"""
    __tablename__ = "account_journal"
    _rec_name = "display_name"
    _book_scoped = True

    code: Mapped[str] = mapped_column(String(10), nullable=False, comment="凭证字代码")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="凭证字名称")
    journal_type: Mapped[str] = mapped_column(String(10), nullable=False, default="general",
                                              comment="类型：general/receipt/payment/transfer")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False, index=True,
                                         comment="所属账套")

    @property
    def display_name(self) -> str:
        return f"{self.name}（{self.code}）"


# ==================== M2：记账核心 ====================

class AccountMove(Base, BaseModelMixin):
    """记账凭证（对标 Odoo account.move，项目书 6.5）。

    状态机：draft -> posted -> voided（红冲）
    - draft：可任意编辑/删除
    - posted：整单只读，唯一出路是红冲
    - voided：被红冲后的原凭证终态
    """
    __tablename__ = "account_move"
    _rec_name = "name"
    _book_scoped = True

    name: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True,
                                             comment="凭证号（过账时由 sequence 生成：记-202609-0001）")
    journal_id: Mapped[int] = mapped_column(ForeignKey("account_journal.id"), nullable=False,
                                            comment="账簿/凭证字")
    move_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="凭证日期")
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True,
                                        comment="所属期间 YYYY-MM（冗余，报表按此过滤）")
    state: Mapped[str] = mapped_column(String(10), nullable=False, default="draft", index=True,
                                       comment="状态：draft/posted/voided")
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual",
                                             comment="来源：manual/auto_invoice/auto_bank/auto_payroll/closing/reversal")
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="附件张数")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备查说明")
    reversed_move_id: Mapped[int | None] = mapped_column(ForeignKey("account_move.id"), nullable=True,
                                                         comment="红冲生成的新凭证（原单指向红冲单）")
    reversed_from_id: Mapped[int | None] = mapped_column(ForeignKey("account_move.id"), nullable=True,
                                                         comment="本凭证由哪张凭证红冲而来（红冲单指回原单）")
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                              comment="是否常用凭证模板（模板不参与账务）")
    template_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="模板名称")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False, index=True,
                                         comment="所属账套")

    @property
    def is_posted(self) -> bool:
        return self.state == "posted"

    @property
    def is_editable(self) -> bool:
        """仅草稿可编辑（posted 后只读，唯一出路是红冲）。"""
        return self.state == "draft"


class AccountMoveLine(Base, BaseModelMixin):
    """凭证分录行（对标 Odoo account.move.line，项目书 6.5）。

    debit/credit 互斥：每行不能同时 > 0（过账校验强制）。
    """
    __tablename__ = "account_move_line"
    _rec_name = "summary"
    _book_scoped = True

    move_id: Mapped[int] = mapped_column(ForeignKey("account_move.id"), nullable=False, index=True,
                                         comment="所属凭证")
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="行号")
    summary: Mapped[str] = mapped_column(String(200), nullable=False, default="",
                                         comment="摘要（中国凭证要素，过账时必填）")
    # 草稿录入允许暂时不选科目（用户可能先填金额后选科目），过账时由 validate_for_post 强制校验
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account_account.id"), nullable=True,
                                                   index=True, comment="科目（过账时必填且须为末级）")
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("res_partner.id"), nullable=True,
                                                   comment="往来单位（科目开 partner 辅助核算时必填）")
    department: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="部门辅助核算")
    project: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="项目辅助核算")
    debit: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0, comment="借方金额（≥0）")
    credit: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0, comment="贷方金额（≥0）")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False, index=True,
                                         comment="所属账套（与凭证一致，冗余以便隔离过滤）")


class AccountPeriodClose(Base, BaseModelMixin):
    """期末结账（期间锁，项目书 6.5）。

    已锁期间禁止新增/修改凭证（跨期补录需先解锁并留审计）。
    """
    __tablename__ = "account_period_close"
    _rec_name = "period"
    _book_scoped = True

    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True, comment="期间 YYYY-MM")
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否已结账锁定")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结账时间")
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="结账备注")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False, index=True,
                                         comment="所属账套")


class AccountTax(Base, BaseModelMixin):
    """税率定义（项目书 6.5），供发票模块与申报计算引用。"""
    __tablename__ = "account_tax"
    _rec_name = "name"
    _book_scoped = True

    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="名称，如 销项税 13%")
    tax_kind: Mapped[str] = mapped_column(String(20), nullable=False,
                                          comment="税种：vat_output/vat_input/surtax/stamp/cit/other")
    rate: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, default=0, comment="税率，如 0.13")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False, index=True,
                                         comment="所属账套")
