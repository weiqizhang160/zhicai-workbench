# -*- coding: utf-8 -*-
"""备份服务（项目书 7.13）：integrity_check → VACUUM INTO → 保留 90 份滚动清理 → 写备份日志。

流程对标 SQLite 官方推荐的热备份方式：
1. PRAGMA integrity_check —— 库有损坏就拒绝备份（备份一个坏库没有意义）；
2. VACUUM INTO '目标路径' —— 生成紧凑的、事务一致的单文件副本，
   与主库 WAL 并发读写互不阻塞（无需停机）；
3. 目标目录：{backup_dir}/zhicai_backup/zhicai_YYYYMMDD_HHMM.db；
4. 滚动清理：只保留最近 backup_keep_copies（默认 90）份，最旧的先删；
5. 每次执行（含跳过/失败）都写一条 backup_log。
"""
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from ...core.config import CONFIG
from ...core.db import SessionLocal
from .models import BackupLog

# 备份子目录名（在 backup_dir 之下，OneDrive 同步范围）
BACKUP_SUBDIR = "zhicai_backup"


def backup_root() -> Path | None:
    """备份根目录；config.yaml 未配置 backup_dir 时返回 None（暂不备份）。"""
    if not (CONFIG.backup_dir or "").strip():
        return None
    return Path(CONFIG.backup_dir.strip()) / BACKUP_SUBDIR


def list_backups() -> list[Path]:
    """备份目录下所有备份文件，按文件名（=时间戳）倒序。"""
    root = backup_root()
    if root is None or not root.exists():
        return []
    return sorted(
        (p for p in root.glob("zhicai_*.db") if p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )


def _write_log(**kwargs) -> None:
    """独立会话写备份日志（即使调用方事务回滚，日志也保留）。"""
    db = SessionLocal()
    try:
        db.add(BackupLog(created_at=datetime.now(), **kwargs))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _cleanup_old(keep: int) -> int:
    """滚动清理：只保留最近 keep 份，返回删除数量。keep<=0 表示不限。"""
    if keep <= 0:
        return 0
    files = list_backups()
    removed = 0
    for p in files[keep:]:
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass  # 文件被占用（如 OneDrive 同步中）——留到下次再清
    return removed


def run_backup(trigger: str = "manual") -> dict:
    """执行一次完整备份流程，返回结果 dict（同时写 backup_log）。

    trigger: startup（每日首次启动）/ timer（每日固定时刻）/ manual（设置页手动）
    未配置备份目录时记 skipped 日志并返回，不报错（首次向导未设置前的正常态）。
    """
    started = time.time()
    now = datetime.now()
    base = {
        "trigger": trigger,
        "file_name": "",
        "file_path": "",
    }

    root = backup_root()
    if root is None:
        result = {**base, "status": "skipped", "message": "未配置备份目录（config.yaml backup_dir）",
                  "integrity": "", "file_size": 0, "duration_ms": 0}
        _write_log(file_name="-", file_path="-", file_size=0, duration_ms=0, integrity="",
                   status="skipped", trigger=trigger,
                   message="未配置备份目录（config.yaml backup_dir）")
        return result

    try:
        root.mkdir(parents=True, exist_ok=True)
        name = f"zhicai_{now:%Y%m%d_%H%M}.db"
        dest = root / name
        if dest.exists():
            dest.unlink()  # 同一分钟重跑：覆盖旧文件

        # 1) 完整性检查（独立连接，不干扰主库会话）
        conn = sqlite3.connect(CONFIG.db_path, timeout=30)
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check")
            row = cur.fetchone()
            integrity = str(row[0]) if row else "unknown"
            if integrity != "ok":
                raise RuntimeError(f"integrity_check 未通过：{integrity}")
            # 2) 热备份（VACUUM INTO 生成事务一致的紧凑副本）
            cur.execute("VACUUM INTO ?", (str(dest),))
        finally:
            conn.close()

        size = dest.stat().st_size
        duration_ms = int((time.time() - started) * 1000)
        removed = _cleanup_old(int(CONFIG.backup_keep_copies or 90))

        msg = f"备份成功，保留 {CONFIG.backup_keep_copies} 份滚动清理"
        if removed:
            msg += f"，本次删除旧备份 {removed} 份"
        _write_log(file_name=name, file_path=str(dest), file_size=size,
                   duration_ms=duration_ms, integrity=integrity,
                   status="ok", trigger=trigger, message=msg)
        return {**base, "status": "ok", "file_name": name, "file_path": str(dest),
                "file_size": size, "duration_ms": duration_ms, "integrity": integrity,
                "removed_old": removed, "message": msg}
    except Exception as exc:  # 备份失败必须留痕，不能静默
        duration_ms = int((time.time() - started) * 1000)
        _write_log(file_name="-", file_path="-", file_size=0, duration_ms=duration_ms,
                   integrity="", status="failed", trigger=trigger, message=str(exc))
        return {**base, "status": "failed", "duration_ms": duration_ms,
                "message": str(exc)}


def backup_history(limit: int = 50) -> list[dict]:
    """最近备份日志（倒序）。"""
    db = SessionLocal()
    try:
        rows = db.query(BackupLog).order_by(BackupLog.id.desc()).limit(limit).all()
        return [{
            "id": r.id, "file_name": r.file_name, "file_path": r.file_path,
            "file_size": r.file_size, "duration_ms": r.duration_ms,
            "integrity": r.integrity, "status": r.status, "trigger": r.trigger,
            "message": r.message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]
    finally:
        db.close()


def db_health() -> dict:
    """数据库健康检查（设置页展示用）：完整性 / 大小 / WAL 状态 / 空闲页。"""
    info: dict = {"db_path": CONFIG.db_path, "ok": True}
    try:
        conn = sqlite3.connect(CONFIG.db_path, timeout=30)
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check")
            info["integrity"] = str(cur.fetchone()[0])
            cur.execute("PRAGMA journal_mode")
            info["journal_mode"] = str(cur.fetchone()[0])
            cur.execute("PRAGMA freelist_count")
            info["freelist_count"] = int(cur.fetchone()[0])
            cur.execute("PRAGMA page_count")
            info["page_count"] = int(cur.fetchone()[0])
        finally:
            conn.close()
        info["db_size"] = Path(CONFIG.db_path).stat().st_size
        info["wal_size"] = (Path(CONFIG.db_path + "-wal").stat().st_size
                            if Path(CONFIG.db_path + "-wal").exists() else 0)
        info["ok"] = info.get("integrity") == "ok"
    except Exception as exc:
        info["ok"] = False
        info["error"] = str(exc)
    info["backups_kept"] = len(list_backups())
    return info
