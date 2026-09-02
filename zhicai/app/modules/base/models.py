# -*- coding: utf-8 -*-
"""base 模块模型（对标 Odoo res.users / res.groups / ir.config_parameter / ir.sequence / mail.message）。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class ResRole(Base, BaseModelMixin):
    """角色（对标 res.groups）。"""
    __tablename__ = "res_role"
    _rec_name = "name"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment="角色代码")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="角色名称")
    permissions: Mapped[str | None] = mapped_column(Text, nullable=True, comment="权限矩阵 JSON")


class ResUsers(Base, BaseModelMixin):
    """登录用户（对标 res.users）。"""
    __tablename__ = "res_users"
    _rec_name = "name"

    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="登录账号")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False, comment="密码哈希")
    role_id: Mapped[int | None] = mapped_column(
        ForeignKey("res_role.id"), nullable=True, comment="角色")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="最后登录")


class IrConfig(Base, BaseModelMixin):
    """键值配置（对标 ir.config_parameter）。"""
    __tablename__ = "ir_config"
    _rec_name = "key"

    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="参数键")
    value: Mapped[str | None] = mapped_column(Text, nullable=True, comment="参数值 JSON")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="说明")


class IrSequence(Base, BaseModelMixin):
    """自动编号器（对标 ir.sequence）。"""
    __tablename__ = "ir_sequence"
    _rec_name = "code"

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="编号器代码")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="名称")
    prefix: Mapped[str] = mapped_column(String(30), nullable=False, default="", comment="前缀")
    padding: Mapped[int] = mapped_column(Integer, nullable=False, default=4, comment="序号位数")
    next_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="下一个序号")
    number_prefix: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="当前序号所在期间（用于按月重置）")
    book_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True, comment="所属账套（空=全局）")


class AuditLog(Base, BaseModelMixin):
    """字段级变更日志（对标 mail.message 的 tracking 部分）。"""
    __tablename__ = "audit_log"
    _book_scoped = False

    model: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="模型表名")
    record_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="记录 ID")
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="操作人")
    action: Mapped[str] = mapped_column(String(20), nullable=False, comment="动作：create/write/动作名")
    changes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="变更明细 JSON")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="时间")


class NoteMessage(Base, BaseModelMixin):
    """记录备注/留言（对标 mail.message 的 note 部分）。"""
    __tablename__ = "note_message"

    model: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="模型表名")
    record_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="记录 ID")
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="留言人")
    body: Mapped[str] = mapped_column(Text, nullable=False, comment="内容")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="时间")
