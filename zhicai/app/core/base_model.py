# -*- coding: utf-8 -*-
"""SQLAlchemy 声明基类与 BaseModel 约定（对标 Odoo models.Model 的字段约定，项目书 5.3.2）。

约定：
- 所有业务模型继承 Base + BaseModelMixin；
- 审计四字段 create_uid/create_date/write_uid/write_date 与 Odoo 同名；
- active=True 有效，删除一律软删除（active=False），物理删除仅限测试；
- _book_scoped = True 的模型必须含 book_id 列，由 CRUD 层自动注入账套隔离过滤；
- _rec_name 指定记录显示名字段（Odoo _rec_name 同思想）。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BaseModelMixin:
    # —— Odoo 式审计字段 ——
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    create_uid: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="创建人")
    create_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="创建时间")
    write_uid: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="最后修改人")
    write_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="最后修改时间")
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="有效标记（软删除）")

    # —— 类级约定（非数据库列） ——
    _book_scoped: bool = False   # True = 查询自动注入当前账套过滤
    _rec_name: str = "name"      # 记录显示名字段

    @classmethod
    def rec_name_of(cls, obj) -> str:
        """返回记录的显示名（供前端下拉/日志显示）。"""
        val = getattr(obj, cls._rec_name, None)
        return str(val) if val is not None else f"{cls.__tablename__}#{obj.id}"
