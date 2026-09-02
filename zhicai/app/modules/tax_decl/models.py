# -*- coding: utf-8 -*-
"""tax_decl 模块：征期规则 + 申报台账（项目书 6.10 / 7.9）。

设计要点：
- 系统**不做自动申报**，只做登记、计算底稿与官网导航（政策安全原因）；
- tax_decl_item 是本模块核心实体，一行 = 一个账套 × 一个税种 × 一个属期；
- calc_snapshot 存计算过程（取数口径 + 公式 + 明细），保证数字可追溯穿透；
- 逾期不是状态而是派生属性：due_date < 今天 且 尚未申报/缴款 → 标红。
"""
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class TaxCalendarRule(Base, BaseModelMixin):
    """征期规则：决定某税种在某类账套下的申报频率与截止日。"""
    __tablename__ = "tax_calendar_rule"
    _rec_name = "name"
    _book_scoped = False      # 规则是全局的（按 applies_to 过滤适用账套）

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="规则名，如 增值税（小规模·按季）")
    tax_kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True,
                                          comment="税种：vat/surtax/cit_quarterly/cit_annual/iit/stamp")
    period_type: Mapped[str] = mapped_column(String(10), nullable=False,
                                             comment="申报频率：monthly/quarterly/yearly")
    deadline_rule: Mapped[str] = mapped_column(String(40), nullable=False,
                                               comment="截止日规则：next_month_15/quarter_next_month_15/annual_0531")
    applies_to: Mapped[str | None] = mapped_column(Text, nullable=True,
                                                   comment="适用账套过滤 JSON，如 {\"taxpayer_type\":\"small\"}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="启用开关")
    is_seed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="内置规则")
    seed_key: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="种子唯一键（幂等）")


class TaxDeclItem(Base, BaseModelMixin):
    """申报台账行（本模块核心实体）。"""
    __tablename__ = "tax_decl_item"
    _rec_name = "display_name"
    _book_scoped = True

    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("res_book.id"), nullable=False,
                                         index=True, comment="所属账套")
    tax_kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True,
                                          comment="税种：vat/surtax/cit_quarterly/cit_annual/iit/stamp")
    period: Mapped[str] = mapped_column(String(10), nullable=False, index=True,
                                        comment="属期：YYYY-MM（月/季）或 YYYY（年度）")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True,
                                                  comment="申报截止日")
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="pending", index=True,
                                       comment="状态：pending/preparing/submitted/paid/done/exempt")

    computed_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0,
                                                   comment="系统计算的应纳税额")
    declared_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True,
                                                          comment="实缴额（标记已申报时填）")
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="缴款日期")
    calc_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True,
                                                      comment="计算底稿 JSON：取数口径 + 公式 + 明细（可追溯）")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注（免税原因等）")
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="auto",
                                        comment="来源：auto 规则生成 / manual 手工补")
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("tax_calendar_rule.id"), nullable=True,
                                                comment="由哪条征期规则生成")

    @property
    def display_name(self) -> str:
        return f"{self.period} {self.tax_kind}"

    @property
    def is_overdue(self) -> bool:
        """逾期：已过截止日且尚未申报（免税/零申报视为已完成，不算逾期）。"""
        if self.state in ("submitted", "paid", "done", "exempt"):
            return False
        if not self.due_date:
            return False
        return self.due_date < date.today()
