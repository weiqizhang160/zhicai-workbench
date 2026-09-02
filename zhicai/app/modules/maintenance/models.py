# -*- coding: utf-8 -*-
"""maintenance 模块模型（项目书 7.13）：备份日志 + 计划任务（对标 Odoo ir.cron）。"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base_model import Base, BaseModelMixin


class BackupLog(Base, BaseModelMixin):
    """备份日志（项目书 7.13：每次备份写日志：时间/大小/结果）。"""
    __tablename__ = "backup_log"
    _book_scoped = False
    _rec_name = "file_name"

    file_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="备份文件名")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="备份绝对路径")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="文件大小(字节)")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="耗时(毫秒)")
    integrity: Mapped[str] = mapped_column(String(10), nullable=False, default="",
                                           comment="integrity_check 结果")
    status: Mapped[str] = mapped_column(String(10), nullable=False, index=True,
                                        comment="ok / skipped / failed")
    trigger: Mapped[str] = mapped_column(String(10), nullable=False, default="manual",
                                         comment="触发方式：startup / timer / manual")
    message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="说明")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="备份时间")


class IrCron(Base, BaseModelMixin):
    """计划任务注册表（对标 Odoo ir.cron）。"""
    __tablename__ = "ir_cron"
    _book_scoped = False
    _rec_name = "code"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, comment="任务代码")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="任务名称")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")
    daily_time: Mapped[str] = mapped_column(String(5), nullable=False, default="00:05",
                                            comment="每日执行时刻 HH:MM")
    last_run_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="最后执行日")
    last_status: Mapped[str | None] = mapped_column(String(10), nullable=True,
                                                    comment="最近一次结果：ok/fail/skipped")
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最近一次结果说明")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="说明")


class IrCronRun(Base, BaseModelMixin):
    """计划任务执行留痕（每次实际执行一条；重复触发当日已跑则不记）。"""
    __tablename__ = "ir_cron_run"
    _book_scoped = False
    _rec_name = "job_code"

    job_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True, comment="任务代码")
    run_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True, comment="执行日")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束时间")
    status: Mapped[str] = mapped_column(String(10), nullable=False, comment="ok / fail")
    trigger: Mapped[str] = mapped_column(String(10), nullable=False, default="timer",
                                         comment="startup / timer / manual")
    result: Mapped[str | None] = mapped_column(Text, nullable=True, comment="结果 JSON")
    message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")
