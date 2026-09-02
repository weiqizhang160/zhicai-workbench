# -*- coding: utf-8 -*-
"""tasks 模块：任务与待办（项目书 6.13 / 7.4 看板）。

设计要点：
- book_id 可空 = 全局任务（不属于任何客户，如"联系新客户"）；
- 任务在总览模式下显示「全局任务 + 全部客户的关联任务」，在指定账套下显示
  「该账套任务 + 全局任务」——因此不走通用 CRUD 的 book scope 自动过滤，
  由 tasks_api 显式控制过滤逻辑；
- source_model/source_id 把任务挂到业务单据（续约提醒→合同、催收→收费计划）。
"""
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class TaskTask(Base, BaseModelMixin):
    """任务 / 待办（对标 Odoo project.task）。"""
    __tablename__ = "task_task"
    _rec_name = "title"
    # 不做自动账套过滤：book_id 可空 = 全局任务，过滤逻辑在 API 层显式处理
    _book_scoped = False

    book_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("res_book.id"),
                                                nullable=True, index=True,
                                                comment="所属账套（空=全局任务）")
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="标题")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True,
                                                  comment="到期日")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal", index=True,
                                          comment="优先级：low/normal/high/urgent")
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="todo", index=True,
                                       comment="状态：todo/doing/done/cancelled")
    assignee_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="负责人（预留）")
    source_model: Mapped[str | None] = mapped_column(String(40), nullable=True,
                                                     comment="来源模型，如 contract_agreement")
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="来源记录 ID")
    reminder_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                comment="到期提醒是否已发送")
