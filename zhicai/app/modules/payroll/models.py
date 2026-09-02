# -*- coding: utf-8 -*-
"""payroll 模块：工资社保（项目书 6.12 / 7.11）。

- payroll_batch 工资批次（按月，每账套每期间唯一）；
- payroll_line 员工行（net_salary = gross − 个人社保 − 个税 自动计算）；
- 个税月度预扣率表存 ir_config（payroll.iit_brackets，可更新）；
- 批次确认后一键生成两张平衡凭证（计提 + 发放）。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class PayrollBatch(Base, BaseModelMixin):
    """工资批次（对标 Odoo hr.payslip.run）。"""
    __tablename__ = "payroll_batch"
    _rec_name = "display_name"
    _book_scoped = True

    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True,
                                        comment="工资期间 YYYY-MM")
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", index=True,
                                       comment="状态：draft 草稿 / confirmed 已确认（已生成凭证）/ paid 已发放")
    employee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
                                                comment="员工人数")
    total_gross: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                 comment="应发合计")
    total_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                               comment="实发合计")
    social_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                 comment="社保基数汇总")
    accrual_move_id: Mapped[int | None] = mapped_column(ForeignKey("account_move.id"),
                                                        nullable=True, comment="计提凭证")
    payment_move_id: Mapped[int | None] = mapped_column(ForeignKey("account_move.id"),
                                                        nullable=True, comment="发放凭证")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套")

    @property
    def display_name(self) -> str:
        return f"{self.period} 工资表"


class PayrollLine(Base, BaseModelMixin):
    """员工月工资行（对标 Odoo hr.payslip）。随批次走，不走通用 CRUD。"""
    __tablename__ = "payroll_line"
    _rec_name = "employee_name"
    _book_scoped = False

    batch_id: Mapped[int] = mapped_column(ForeignKey("payroll_batch.id"), nullable=False,
                                          index=True, comment="所属批次")
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套（冗余）")
    employee_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="员工姓名")
    id_card_tail: Mapped[str | None] = mapped_column(String(8), nullable=True,
                                                     comment="证件号后四位")
    gross_salary: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                  comment="应发工资")
    social_employee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                     comment="个人社保（含个人公积金）")
    social_employer: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                     comment="单位社保")
    fund_employer: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                   comment="单位公积金")
    iit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                         comment="代扣个税")
    net_salary: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                comment="实发（自动计算）")
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="备注")
