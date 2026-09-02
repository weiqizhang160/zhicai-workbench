# -*- coding: utf-8 -*-
"""auto_entry 模块：自动记账规则与执行日志（项目书 6.9，对标 Odoo account.reconcile.model）。

核心设计：
- match_condition（JSON）：决定这条规则对哪些源单据生效；
- line_template（JSON）：分录模板，支持 {字段} 变量与 ={x}*0.13 表达式；
- 引擎生成凭证前强制校验借贷平衡，不平衡整单拒绝并写日志；
- 幂等由源单据自身状态保证（发票 entry_generated / 流水 reconciled）。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class AutoEntryRule(Base, BaseModelMixin):
    """自动记账规则（对标 Odoo account.reconcile.model）。"""
    __tablename__ = "auto_entry_rule"
    _rec_name = "name"
    _book_scoped = True

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="规则名，如 销项专票→确认收入")
    trigger: Mapped[str] = mapped_column(String(30), nullable=False, index=True,
                                         comment="触发源：invoice_output / invoice_input / bank_line / payroll")
    match_condition: Mapped[str | None] = mapped_column(Text, nullable=True,
                                                        comment="过滤条件 JSON，如 {\"invoice_type\":\"special\"}")
    journal_code: Mapped[str] = mapped_column(String(10), nullable=False, default="记",
                                              comment="生成凭证使用的凭证字")
    line_template: Mapped[str] = mapped_column(Text, nullable=False,
                                               comment="分录模板 JSON：[{side, account, summary, amount}]")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100,
                                          comment="优先级，小者优先（多规则命中时取第一个）")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="启用开关")
    is_seed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                          comment="是否系统内置种子规则（seed 幂等用）")
    seed_key: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="种子规则唯一键（幂等）")
    book_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=True,
                                                index=True,
                                                comment="所属账套；NULL = 全局通用规则（所有账套可见）")


class AutoEntryLog(Base, BaseModelMixin):
    """规则执行日志（成功失败都可追溯）。"""
    __tablename__ = "auto_entry_log"
    _rec_name = "name"
    _book_scoped = False   # 日志按 book_id 手动过滤，避免总览模式被拦截

    rule_id: Mapped[int | None] = mapped_column(ForeignKey("auto_entry_rule.id"), nullable=True,
                                                comment="命中的规则（未命中时为 NULL）")
    source_model: Mapped[str] = mapped_column(String(30), nullable=False, comment="源单据模型：invoice_bill / bank_statement_line")
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="源单据 id")
    result: Mapped[str] = mapped_column(String(10), nullable=False, comment="结果：ok / failed / skipped")
    move_id: Mapped[int | None] = mapped_column(ForeignKey("account_move.id"), nullable=True,
                                                comment="生成的凭证（成功时）")
    message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="说明/错误信息")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="执行时间")
    book_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=True,
                                                index=True, comment="所属账套")

    @property
    def name(self) -> str:
        return f"{self.source_model}#{self.source_id} {self.result}"
