# -*- coding: utf-8 -*-
"""bank 模块：银行流水与对账（项目书 6.8）。

注意银行视角的借贷方向与会计相反：
- debit  = 收入（钱进账，银行对账单的"贷方发生额"，但存 debit 字段表示收入）
- credit = 支出（钱出账）
生成凭证时由 auto_entry 规则决定会计分录方向。
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class BankStatement(Base, BaseModelMixin):
    """对账单导入批次（一次导入 = 一个批次，便于整批撤销与统计）。"""
    __tablename__ = "bank_statement"
    _rec_name = "display_name"
    _book_scoped = True

    bank_alias: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="银行简称，如 工行/建行/招行")
    account_no: Mapped[str | None] = mapped_column(String(40), nullable=True, comment="银行账号（后 4 位或完整）")
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True, comment="所属期间 YYYY-MM")
    imported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="导入时间")
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="流水行数")
    total_debit: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0, comment="收入合计")
    total_credit: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0, comment="支出合计")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套")

    @property
    def display_name(self) -> str:
        return f"{self.bank_alias or '银行'} {self.period}（{self.line_count} 行）"


class BankStatementLine(Base, BaseModelMixin):
    """银行流水行：对账工作台的数据源。"""
    __tablename__ = "bank_statement_line"
    _rec_name = "summary"
    _book_scoped = True

    statement_id: Mapped[int] = mapped_column(ForeignKey("bank_statement.id"), nullable=False,
                                              index=True, comment="所属导入批次")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="交易日期")
    trade_no: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="银行流水号（用于对账追溯）")
    counterpart_name: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="对方户名")
    summary: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="交易摘要（规则匹配主要依据）")
    debit: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0, comment="收入金额（钱进账）")
    credit: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0, comment="支出金额（钱出账）")
    balance: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True, comment="交易后余额")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="unreconciled", index=True,
                                       comment="对账状态：unreconciled 未对账 / reconciled 已对账")
    move_id: Mapped[int | None] = mapped_column(ForeignKey("account_move.id"), nullable=True,
                                                comment="生成的凭证（与 state 联动）")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套")

    @property
    def can_generate_entry(self) -> bool:
        """未对账的流水才能生成凭证（幂等基础）。"""
        return self.state == "unreconciled"
