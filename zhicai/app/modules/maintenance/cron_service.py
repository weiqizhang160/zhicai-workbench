# -*- coding: utf-8 -*-
"""计划任务框架（项目书 7.13，对标 Odoo ir.cron）。

设计：
- 任务注册表存 ir_cron（code 唯一），任务实现在本文件的 JOB_FUNCS；
- 每个任务有 daily_time（HH:MM，可改），每天最多自动执行一次；
- 启动补跑：服务启动时（对标「每日 00:05 补跑」），凡 last_run_date < 今日
  的启用任务立即执行——覆盖「每日首次启动备份」「错过整点补跑」两个场景；
- 定时循环：后台线程每分钟检查，daily_time 已到且今日未跑则执行；
- 执行留痕：每次实际执行写一条 ir_cron_run（含结果 JSON / 错误信息）。

内置任务（项目书 7.13）：
- backup          每日自动备份（integrity_check → VACUUM INTO → 滚动清理）
- decl_generate   每日生成上月申报台账（generate_items 幂等，已存在跳过）
- fee_overdue     每日逾期扫描 + 续约提醒（scan_overdue_and_renewal）
- task_reminder   每日任务到期提醒（3 天内到期或已逾期 → 标记已提醒）
"""
import json
import os
import threading
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.db import SessionLocal
from ...core.errors import BizError
from ..tasks.models import TaskTask
from .models import IrCron, IrCronRun

# ==================== 任务实现 ====================


def _job_backup(db: Session, trigger: str) -> dict:
    from .backup_service import run_backup
    return run_backup(trigger=trigger)


def _job_decl_generate(db: Session, trigger: str) -> dict:
    """生成「上一个自然月」属期的申报台账（幂等：已存在的 (账套,税种,属期) 跳过）。"""
    from ..tax_decl.calendar_service import generate_items
    prev_month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    try:
        return generate_items(db, [prev_month])
    except BizError as exc:  # 空库/无规则不算失败，记说明即可
        return {"status": "skipped", "message": exc.message}


def _job_fee_overdue(db: Session, trigger: str) -> dict:
    """逾期收费标记 + 催收任务 + 到期前 30 天续约提醒（幂等）。"""
    from ..contract.service import scan_overdue_and_renewal
    return scan_overdue_and_renewal(db)


def _job_task_reminder(db: Session, trigger: str) -> dict:
    """到期任务提醒：3 天内到期或已逾期、未提醒过的进行中任务 → 标记 reminder_sent。"""
    today = date.today()
    rows = db.execute(
        select(TaskTask).where(
            TaskTask.active.is_(True),
            TaskTask.state.in_(["todo", "doing"]),
            TaskTask.reminder_sent.is_(False),
            TaskTask.due_date.isnot(None),
            TaskTask.due_date <= today + timedelta(days=3),
        )
    ).scalars().all()
    for t in rows:
        t.reminder_sent = True
    titles = [t.title for t in rows[:10]]
    return {"reminded": len(rows), "titles": titles}


# 任务注册表：code → 实现（ir_cron 表里的 code 必须在这里有对应实现）
JOB_FUNCS = {
    "backup": _job_backup,
    "decl_generate": _job_decl_generate,
    "fee_overdue": _job_fee_overdue,
    "task_reminder": _job_task_reminder,
}


# ==================== 执行与留痕 ====================


def run_job(db: Session, code: str, trigger: str = "manual", force: bool | None = None) -> dict:
    """执行一个计划任务并留痕。

    - force=None 时：手动触发（manual）默认强制跑，定时/启动触发尊重「每日一次」；
    - 任务抛异常：回滚业务改动，再单独记录一条 fail 的 ir_cron_run；
    - 返回 {"status": ok/fail/skipped, ...}。
    """
    job = db.execute(select(IrCron).where(IrCron.code == code)).scalar_one_or_none()
    if job is None:
        raise BizError("cron_not_found", f"计划任务不存在：{code}")
    today = date.today()
    forced = (trigger == "manual") if force is None else force
    if not forced and job.last_run_date == today:
        return {"status": "skipped", "job": code, "reason": "今日已执行"}

    func = JOB_FUNCS.get(code)
    if func is None:
        raise BizError("cron_not_implemented", f"任务未实现：{code}")

    started = datetime.now()
    try:
        result = func(db, trigger)
        db.flush()
    except Exception as exc:
        db.rollback()
        job = db.execute(select(IrCron).where(IrCron.code == code)).scalar_one()
        db.add(IrCronRun(
            job_code=code, run_date=today, started_at=started,
            finished_at=datetime.now(), status="fail", trigger=trigger,
            message=str(exc)[:2000], active=True,
        ))
        job.last_run_date = today
        job.last_status = "fail"
        job.last_message = str(exc)[:500]
        db.commit()
        return {"status": "fail", "job": code, "error": str(exc)}

    db.add(IrCronRun(
        job_code=code, run_date=today, started_at=started,
        finished_at=datetime.now(), status="ok", trigger=trigger,
        result=json.dumps(result, ensure_ascii=False, default=str)[:4000], active=True,
    ))
    job.last_run_date = today
    job.last_status = "ok"
    job.last_message = json.dumps(result, ensure_ascii=False, default=str)[:500]
    db.commit()
    return {"status": "ok", "job": code, "result": result}


def _now_hhmm() -> str:
    return datetime.now().strftime("%H:%M")


def run_due_jobs(trigger: str) -> list[dict]:
    """跑所有「今日未执行且时刻已到」的启用任务（补跑/定时共用）。

    - trigger=startup：不看 daily_time，错过的全部补跑；
    - trigger=timer：只跑 daily_time 已到的。
    """
    out: list[dict] = []
    db = SessionLocal()
    try:
        jobs = db.execute(select(IrCron).where(IrCron.active.is_(True))).scalars().all()
        now_hhmm = _now_hhmm()
        today = date.today()
        due = []
        for job in jobs:
            if job.last_run_date == today:
                continue
            if trigger == "timer" and (job.daily_time or "00:05") > now_hhmm:
                continue
            due.append(job.code)
        db.rollback()  # 查询会话释放，任务用独立事务跑
    finally:
        db.close()

    for code in due:
        db = SessionLocal()
        try:
            out.append(run_job(db, code, trigger=trigger))
        finally:
            db.close()
    return out


# ==================== 后台线程（对标 Odoo ir.cron 调度器） ====================

_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()
CHECK_INTERVAL = 60  # 秒


def _loop() -> None:
    """调度循环：启动先补跑错过的任务，之后每分钟检查到点任务。"""
    try:
        run_due_jobs("startup")
    except Exception:
        pass  # 单个任务的失败已留痕；调度循环不能死
    while not _stop.wait(CHECK_INTERVAL):
        try:
            run_due_jobs("timer")
        except Exception:
            pass


def start_scheduler() -> None:
    """启动调度线程（幂等）。测试环境用 ZC_DISABLE_SCHEDULER=1 关闭。"""
    global _thread
    if os.environ.get("ZC_DISABLE_SCHEDULER") == "1":
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="zc-cron", daemon=True)
        _thread.start()


def stop_scheduler() -> None:
    """停止调度线程（仅测试/关停用）。"""
    global _thread
    _stop.set()
    with _lock:
        _thread = None


# ==================== 查询（API 用） ====================


def cron_overview(db: Session, run_limit: int = 20) -> dict:
    """任务列表 + 最近执行留痕 + 调度器状态。"""
    jobs = db.execute(select(IrCron).order_by(IrCron.id)).scalars().all()
    runs = db.execute(
        select(IrCronRun).order_by(IrCronRun.id.desc()).limit(run_limit)
    ).scalars().all()
    with _lock:
        thread_alive = _thread is not None and _thread.is_alive()
    return {
        "jobs": [{
            "id": j.id, "code": j.code, "name": j.name, "active": j.active,
            "daily_time": j.daily_time,
            "last_run_date": j.last_run_date.isoformat() if j.last_run_date else None,
            "last_status": j.last_status, "last_message": j.last_message,
            "remark": j.remark,
        } for j in jobs],
        "runs": [{
            "id": r.id, "job_code": r.job_code, "run_date": r.run_date.isoformat() if r.run_date else None,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status, "trigger": r.trigger, "result": r.result, "message": r.message,
        } for r in runs],
        "scheduler_running": thread_alive,
        "disabled_by_env": os.environ.get("ZC_DISABLE_SCHEDULER") == "1",
    }
