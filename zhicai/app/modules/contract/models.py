# -*- coding: utf-8 -*-
"""contract 模块：代账合同 + 收费计划（项目书 6.13 / 7.4）。

设计要点：
- contract_agreement = 一份代账服务合同（对标 Odoo subscription），按账套隔离；
- contract_fee_item = 收费计划/收款记录，一行 = 一个合同 × 一个收费期；
- 金额一律 Decimal（项目书约定，禁 float）；
- 「逾期」既在 state 里保留 overdue 枚举值（扫描任务显式打标），
  又提供派生属性 is_overdue（unpaid/invoiced 且已过 due_date 即视为逾期），
  保证仪表盘「逾期未收」口径正确（项目书 7.4 DoD）。
"""
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class ContractAgreement(Base, BaseModelMixin):
    """代账服务合同。"""
    __tablename__ = "contract_agreement"
    _rec_name = "contract_no"
    _book_scoped = True

    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套")
    contract_no: Mapped[str] = mapped_column(String(40), nullable=False, index=True,
                                             comment="合同编号（ir_sequence 生成）")
    sign_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="签订日期")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="服务开始日期")
    end_date: Mapped[date] = mapped_column(Date, nullable=False, comment="服务结束日期")
    service_scope: Mapped[str | None] = mapped_column(Text, nullable=True,
                                                      comment="服务范围 JSON 多选：记账/报税/工商年检/出口退税…")
    fee_type: Mapped[str] = mapped_column(String(10), nullable=False, default="monthly",
                                          comment="收费周期：monthly/quarterly/annual")
    fee_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                              comment="每期收费金额")
    payer_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="付款方名称")
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="active", index=True,
                                       comment="状态：active/expired/terminated")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    @property
    def is_expiring(self) -> bool:
        """到期前 30 天内（含已到期未终止）视为临期，用于续约提醒。"""
        if self.state != "active" or not self.end_date:
            return False
        from datetime import timedelta
        return date.today() >= self.end_date - timedelta(days=30)


class ContractFeeItem(Base, BaseModelMixin):
    """收费计划 / 收款记录。"""
    __tablename__ = "contract_fee_item"
    _rec_name = "display_name"
    _book_scoped = True

    agreement_id: Mapped[int] = mapped_column(Integer, ForeignKey("contract_agreement.id"),
                                              nullable=False, index=True, comment="所属合同")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True,
                                         comment="所属账套（冗余，自合同继承，便于隔离与跨账套聚合）")
    period: Mapped[str] = mapped_column(String(10), nullable=False, index=True,
                                        comment="收费期：YYYY-MM / YYYYQn / YYYY")
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                          comment="本期应收金额")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True,
                                                  comment="本期收款到期日")
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="unpaid", index=True,
                                       comment="状态：unpaid/invoiced/paid/overdue")
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="收款日期")
    paid_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True,
                                                      comment="实收金额")
    invoice_no: Mapped[str | None] = mapped_column(String(40), nullable=True, comment="发票号码")

    @property
    def display_name(self) -> str:
        return f"{self.period} ¥{self.amount}"

    @property
    def is_overdue(self) -> bool:
        """逾期：已过到期日且未收清（paid 之外的状态都算未收）。"""
        if self.state == "paid":
            return False
        if not self.due_date:
            return False
        return self.due_date < date.today()
