# -*- coding: utf-8 -*-
"""board 模块：仪表盘卡片配置（项目书 6.13 / 7.2）。

board_card 是全局表（无 book_id）：控制首页工作台各卡片的显示顺序、启用与
附加配置（如某张卡片是否折叠、显示条数）。卡片本体数据由 dashboard_api 聚合。
"""
from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class BoardCard(Base, BaseModelMixin):
    """仪表盘卡片配置。"""
    __tablename__ = "board_card"
    _rec_name = "card_key"
    _book_scoped = False

    card_key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True,
                                          comment="卡片键：overview/decl_alert/overdue/todo_tasks/fee_month/client_progress")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="显示顺序")
    config: Mapped[str | None] = mapped_column(Text, nullable=True, comment="附加配置 JSON")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否显示")
