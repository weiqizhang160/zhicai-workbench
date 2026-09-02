# -*- coding: utf-8 -*-
"""maintenance 模块种子数据：注册 4 个内置计划任务（项目书 7.13，幂等）。"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import IrCron

# (code, name, daily_time, remark)
BUILTIN_JOBS = [
    ("backup", "每日自动备份", "09:00",
     "integrity_check → VACUUM INTO 到备份目录 → 保留最近 90 份；启动时当日未备份会立即补跑"),
    ("decl_generate", "生成上月申报台账", "00:30",
     "按征期规则批量生成上一自然月的申报台账（幂等，已存在的跳过）"),
    ("fee_overdue", "逾期与续约扫描", "07:00",
     "逾期代账费标记 + 生成催收任务；合同到期前 30 天生成续约提醒"),
    ("task_reminder", "任务到期提醒", "07:30",
     "3 天内到期或已逾期的进行中任务标记已提醒"),
]


def seed(db: Session) -> None:
    existed = {r[0] for r in db.execute(select(IrCron.code)).all()}
    now = datetime.now()
    for code, name, daily_time, remark in BUILTIN_JOBS:
        if code in existed:
            continue
        db.add(IrCron(
            code=code, name=name, active=True, daily_time=daily_time,
            remark=remark, create_date=now, write_date=now,
        ))
    db.flush()
