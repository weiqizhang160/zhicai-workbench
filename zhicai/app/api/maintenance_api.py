# -*- coding: utf-8 -*-
"""运维 API（M7，项目书 7.13/7.14）：立即备份 / 备份历史 / 数据库健康 / 计划任务 / 全量导出。"""
import csv
import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.errors import BizError
from ..core.registry import REGISTRY
from ..modules.base.models import ResUsers
from ..modules.maintenance import backup_service, cron_service
from ..modules.maintenance.models import IrCron
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])


# ==================== 备份 ====================

@router.post("/backup/run")
def run_backup(user: ResUsers = Depends(require_role("create")),
               db: Session = Depends(get_db)):
    """手动立即备份（设置页「立即备份」按钮）。"""
    _ = db  # 备份流程用独立连接/会话，不经请求事务
    result = backup_service.run_backup(trigger="manual")
    if result.get("status") == "failed":
        raise BizError("backup_failed", f"备份失败：{result.get('message')}")
    return {"ok": True, "result": result}


@router.get("/backup/logs")
def backup_logs(limit: int = 50,
                user: ResUsers = Depends(require_login),
                db: Session = Depends(get_db)):
    """备份历史（倒序）。"""
    _ = db
    return {"items": backup_service.backup_history(limit=limit)}


@router.get("/backup/files")
def backup_files(user: ResUsers = Depends(require_login),
                 db: Session = Depends(get_db)):
    """备份目录现有文件（恢复引导用：按时间倒序）。"""
    _ = db
    root = backup_service.backup_root()
    items = [{
        "file_name": p.name,
        "file_size": p.stat().st_size,
        "mtime": p.stat().st_mtime,
    } for p in backup_service.list_backups()]
    return {"backup_dir": str(root) if root else None, "items": items}


# ==================== 数据库健康 ====================

@router.get("/db/health")
def db_health(user: ResUsers = Depends(require_login),
              db: Session = Depends(get_db)):
    """数据库健康检查：完整性 / 大小 / WAL / 备份数。"""
    _ = db
    return backup_service.db_health()


# ==================== 计划任务 ====================

@router.get("/cron")
def cron_overview(user: ResUsers = Depends(require_login),
                  db: Session = Depends(get_db)):
    """任务列表 + 最近执行留痕 + 调度器状态。"""
    return cron_service.cron_overview(db)


@router.post("/cron/{code}/run")
def cron_run(code: str, user: ResUsers = Depends(require_role("create")),
             db: Session = Depends(get_db)):
    """手动触发某个任务（强制执行，不受「每日一次」限制）。"""
    if code not in cron_service.JOB_FUNCS:
        raise BizError("cron_not_found", f"未知计划任务：{code}")
    result = cron_service.run_job(db, code, trigger="manual", force=True)
    if result.get("status") == "fail":
        raise BizError("cron_failed", f"任务执行失败：{result.get('error')}")
    return {"ok": True, "result": result}


class CronUpdate(BaseModel):
    daily_time: str | None = None
    active: bool | None = None


@router.put("/cron/{code}")
def cron_update(code: str, body: CronUpdate,
                user: ResUsers = Depends(require_role("write")),
                db: Session = Depends(get_db)):
    """修改任务配置：每日时刻 / 启用停用。"""
    job = db.query(IrCron).filter(IrCron.code == code).first()
    if job is None:
        raise BizError("cron_not_found", f"计划任务不存在：{code}")
    if body.daily_time is not None:
        hh, _, mm = body.daily_time.partition(":")
        if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise BizError("bad_time", "时间格式应为 HH:MM（00:00–23:59）")
        job.daily_time = f"{int(hh):02d}:{int(mm):02d}"
    if body.active is not None:
        job.active = body.active
    job.write_uid = user.id
    job.write_date = datetime.now()
    db.flush()
    return {"ok": True, "job": {"code": job.code, "daily_time": job.daily_time,
                                "active": job.active}}


# ==================== 全量导出（CSV 包，项目书 7.14） ====================

def _csv_cell(v) -> str:
    """把任意字段值转成 CSV 单元格文本。"""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, bool):
        return "1" if v else ""
    return str(v)


@router.get("/export/csv")
def export_csv(user: ResUsers = Depends(require_role("read")),
               db: Session = Depends(get_db)):
    """导出全量数据：注册表内所有表各生成一个 CSV，打包成 zip 下载。"""
    buf = io.BytesIO()
    tables = 0
    rows_total = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for mod_name in REGISTRY.topological_order(REGISTRY.modules):
            for table, cls in REGISTRY.modules[mod_name].models.items():
                cols = [c.key for c in cls.__table__.columns]
                sio = io.StringIO()
                writer = csv.writer(sio)
                writer.writerow(cols)
                n = 0
                for obj in db.execute(select(cls)).scalars():
                    writer.writerow([_csv_cell(getattr(obj, c)) for c in cols])
                    n += 1
                zf.writestr(f"{table}.csv", "\ufeff" + sio.getvalue())  # BOM：Excel 直开不乱码
                tables += 1
                rows_total += n
    now = datetime.now()
    fname = f"zhicai_export_{now:%Y%m%d_%H%M}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Export-Tables": str(tables),
            "X-Export-Rows": str(rows_total),
        },
    )
