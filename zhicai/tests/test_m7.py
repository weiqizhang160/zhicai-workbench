# -*- coding: utf-8 -*-
"""M7 测试（一）：备份与计划任务（项目书 7.13 DoD）。"""
from datetime import date, datetime, timedelta

import pytest

from app.core.config import CONFIG
from app.core.db import SessionLocal
from app.modules.maintenance import backup_service, cron_service
from app.modules.maintenance.models import BackupLog, IrCron, IrCronRun
from app.modules.tasks.models import TaskTask


@pytest.fixture(scope="module", autouse=True)
def _ensure_app(client):
    """确保本模块所有测试跑之前应用已启动（建表+种子）——
    TestBackup 不直接用 client，但 backup_log / ir_cron 表得先存在。"""
    yield


@pytest.fixture()
def backup_dir(tmp_path, monkeypatch):
    """把备份目录指到临时目录，不动真实 OneDrive 配置。"""
    monkeypatch.setattr(CONFIG, "backup_dir", str(tmp_path / "onedrive"))
    monkeypatch.setattr(CONFIG, "backup_keep_copies", 90)
    return tmp_path / "onedrive"


# ==================== 备份 ====================

class TestBackup:

    def test_backup_skipped_without_dir(self, monkeypatch):
        """未配置 backup_dir：记 skipped 日志，不报错。"""
        monkeypatch.setattr(CONFIG, "backup_dir", "")
        result = backup_service.run_backup(trigger="manual")
        assert result["status"] == "skipped"
        db = SessionLocal()
        try:
            assert db.query(BackupLog).filter(BackupLog.status == "skipped").count() >= 1
        finally:
            db.close()

    def test_backup_ok_and_logged(self, backup_dir):
        """正常备份：integrity_check 通过 → VACUUM INTO 生成文件 → 写日志。"""
        result = backup_service.run_backup(trigger="manual")
        assert result["status"] == "ok", result
        assert result["integrity"] == "ok"
        assert result["file_size"] > 0
        from pathlib import Path
        f = Path(result["file_path"])
        assert f.exists() and f.parent.name == "zhicai_backup"
        assert f.name.startswith("zhicai_") and f.name.endswith(".db")

        # 备份文件本身是合法 SQLite 库（恢复演练的基础）
        import sqlite3
        conn = sqlite3.connect(str(f))
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        assert {"res_book", "account_move", "ir_cron"} <= tables

        db = SessionLocal()
        try:
            log = db.query(BackupLog).filter(BackupLog.file_name == f.name).one()
            assert log.status == "ok" and log.integrity == "ok"
            assert log.file_size == result["file_size"]
        finally:
            db.close()

    def test_backup_rolling_cleanup(self, backup_dir, monkeypatch):
        """滚动清理：只保留最近 N 份（默认 90，此处用 2 验证）。"""
        root = backup_service.backup_root()
        root.mkdir(parents=True, exist_ok=True)
        # 造 5 个旧备份（文件名即时间戳，可排序）
        for i in range(1, 6):
            (root / f"zhicai_2026010{i}_0000.db").write_bytes(b"old")
        monkeypatch.setattr(CONFIG, "backup_keep_copies", 2)

        result = backup_service.run_backup(trigger="manual")
        assert result["status"] == "ok"
        assert result.get("removed_old") == 4          # 5 旧 - 1 保留
        files = backup_service.list_backups()
        assert len(files) == 2                          # 新备份 + 最旧的 1 份旧备份
        assert files[0].name == result["file_name"]     # 倒序：最新在前

    def test_backup_history(self, backup_dir):
        backup_service.run_backup(trigger="manual")
        history = backup_service.backup_history(limit=10)
        assert len(history) >= 1
        assert history[0]["status"] == "ok"

    def test_db_health(self, backup_dir):
        info = backup_service.db_health()
        assert info["ok"] is True
        assert info["integrity"] == "ok"
        assert info["journal_mode"].lower() == "wal"
        assert info["db_size"] > 0


# ==================== 计划任务 ====================

class TestCronFramework:

    def test_seed_creates_builtin_jobs(self, client):
        """启动即注册 4 个内置任务（backup / decl_generate / fee_overdue / task_reminder）。"""
        db = SessionLocal()
        try:
            codes = {r[0] for r in db.query(IrCron.code).all()}
        finally:
            db.close()
        assert {"backup", "decl_generate", "fee_overdue", "task_reminder"} <= codes

    def test_task_reminder_job(self, client):
        """task_reminder：3 天内到期未提醒的任务 → 标记已提醒并留痕。"""
        db = SessionLocal()
        try:
            t = TaskTask(title="M7 测试任务：两天后到期", state="todo",
                         due_date=date.today() + timedelta(days=2),
                         reminder_sent=False, active=True)
            db.add(t)
            far = TaskTask(title="不会提醒：一个月后到期", state="todo",
                           due_date=date.today() + timedelta(days=30),
                           reminder_sent=False, active=True)
            db.add(far)
            db.commit()
            tid, fid = t.id, far.id

            result = cron_service.run_job(db, "task_reminder", trigger="timer")
            assert result["status"] == "ok"
            assert result["result"]["reminded"] >= 1

            db.expire_all()
            assert db.get(TaskTask, tid).reminder_sent is True
            assert db.get(TaskTask, fid).reminder_sent is False

            # 留痕
            run = db.query(IrCronRun).filter(IrCronRun.job_code == "task_reminder") \
                .order_by(IrCronRun.id.desc()).first()
            assert run.status == "ok" and run.trigger == "timer"
        finally:
            db.close()

    def test_daily_once_and_force(self, client):
        """每日一次：当日已跑 → timer 触发 skipped；manual 强制重跑。"""
        db = SessionLocal()
        try:
            r1 = cron_service.run_job(db, "fee_overdue", trigger="timer")
            assert r1["status"] == "ok"
            r2 = cron_service.run_job(db, "fee_overdue", trigger="timer")
            assert r2["status"] == "skipped"
            r3 = cron_service.run_job(db, "fee_overdue", trigger="manual")
            assert r3["status"] == "ok"    # 手动触发默认强制
        finally:
            db.close()

    def test_decl_generate_job(self, client):
        """decl_generate：生成上一自然月的申报台账（幂等）。"""
        db = SessionLocal()
        try:
            prev = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
            r1 = cron_service.run_job(db, "decl_generate", trigger="timer")
            assert r1["status"] == "ok"
            created = r1["result"].get("created", 0) + r1["result"].get("skipped", 0)
            assert created >= 0
            # 再跑一次：全部 skipped（幂等）
            r2 = cron_service.run_job(db, "decl_generate", trigger="manual")
            assert r2["status"] == "ok"
        finally:
            db.close()

    def test_run_unknown_job_raises(self, client):
        from app.core.errors import BizError
        db = SessionLocal()
        try:
            with pytest.raises(BizError):
                cron_service.run_job(db, "no_such_job", trigger="manual")
        finally:
            db.close()

    def _reset_last_run(self):
        """把全部任务的 last_run_date 清空（模拟「昨天跑过、今天还没跑」）。"""
        db = SessionLocal()
        try:
            db.query(IrCron).update({"last_run_date": None})
            db.commit()
        finally:
            db.close()

    def test_run_due_jobs_catchup(self, client, backup_dir):
        """启动补跑：所有「今日未跑」的启用任务被执行并留痕。"""
        self._reset_last_run()
        results = cron_service.run_due_jobs("startup")
        statuses = {r.get("job"): r.get("status") for r in results}
        assert set(statuses) == {"backup", "decl_generate", "fee_overdue", "task_reminder"}
        assert all(s == "ok" for s in statuses.values())
        # 补跑后当日再触发：全部 skipped（run_due_jobs 直接返回空）
        again = cron_service.run_due_jobs("timer")
        assert again == []

    def test_disabled_jobs_not_run(self, client):
        """停用的任务不参与调度。"""
        self._reset_last_run()
        db = SessionLocal()
        try:
            db.query(IrCron).filter(IrCron.code == "task_reminder") \
                .update({"active": False})
            db.commit()
        finally:
            db.close()
        results = cron_service.run_due_jobs("startup")
        ran = {r.get("job") for r in results}
        assert "task_reminder" not in ran
        assert "backup" in ran          # 其他任务照常补跑


# ==================== API ====================

class TestMaintenanceAPI:

    def test_backup_run_api(self, client, backup_dir):
        r = client.post("/api/v1/maintenance/backup/run")
        assert r.status_code == 200, r.text
        assert r.json()["result"]["status"] == "ok"

    def test_backup_logs_api(self, client, backup_dir):
        client.post("/api/v1/maintenance/backup/run")
        r = client.get("/api/v1/maintenance/backup/logs")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) >= 1 and items[0]["status"] == "ok"

    def test_backup_files_api(self, client, backup_dir):
        backup_service.run_backup(trigger="manual")
        r = client.get("/api/v1/maintenance/backup/files")
        assert r.status_code == 200
        body = r.json()
        assert body["backup_dir"] and len(body["items"]) >= 1

    def test_db_health_api(self, client):
        r = client.get("/api/v1/maintenance/db/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_cron_overview_api(self, client):
        r = client.get("/api/v1/maintenance/cron")
        assert r.status_code == 200
        body = r.json()
        assert len(body["jobs"]) >= 4
        assert body["disabled_by_env"] is True   # 测试环境关掉了调度线程

    def test_cron_manual_run_api(self, client):
        r = client.post("/api/v1/maintenance/cron/fee_overdue/run")
        assert r.status_code == 200, r.text
        assert r.json()["result"]["status"] == "ok"

    def test_cron_run_unknown_api(self, client):
        r = client.post("/api/v1/maintenance/cron/no_such/run")
        assert r.status_code == 400

    def test_cron_update_api(self, client):
        r = client.put("/api/v1/maintenance/cron/task_reminder",
                       json={"daily_time": "08:15"})
        assert r.status_code == 200
        assert r.json()["job"]["daily_time"] == "08:15"

        bad = client.put("/api/v1/maintenance/cron/task_reminder",
                         json={"daily_time": "25:99"})
        assert bad.status_code == 400

    def test_maintenance_requires_login(self, fresh_client):
        assert fresh_client.get("/api/v1/maintenance/cron").status_code == 401
        assert fresh_client.post("/api/v1/maintenance/backup/run").status_code == 401


# ==================== M7-2 设置页：菜单 / 导出 / 审计筛选 ====================

class TestSettingsPage:

    def test_settings_menu_registered(self, client):
        r = client.get("/api/v1/meta/menu")
        labels = [m["label"] for m in r.json()["menus"]]
        assert "系统设置" in labels
        settings = [m for m in r.json()["menus"] if m["label"] == "系统设置"][0]
        assert settings.get("route") == "#/settings"

    def test_export_csv_package(self, client):
        """全量导出：zip 包含所有注册表的 CSV（带 BOM，Excel 直开不乱码）。"""
        import io
        import zipfile
        r = client.get("/api/v1/maintenance/export/csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/zip")
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        assert {"res_book.csv", "account_move.csv", "ir_cron.csv",
                "backup_log.csv", "doc_document.csv"} <= set(names)
        head = zf.read("res_book.csv").decode("utf-8-sig").splitlines()[0]
        assert "id" in head and "short_name" in head
        # 行数应与库中一致（含表头）
        body = zf.read("ir_cron.csv").decode("utf-8-sig").splitlines()
        assert len(body) >= 5  # 表头 + 4 个内置任务

    def test_audit_log_domain_filter(self, client):
        """审计日志按模型筛选（设置页审计 Tab 的后端能力）。"""
        import json as _json
        r = client.get("/api/v1/data/audit_log", params={
            "domain": _json.dumps([["model", "ilike", "res_book"]]), "limit": 10})
        assert r.status_code == 200
        items = r.json()["records"]
        assert all("res_book" in it["model"] for it in items)

    def test_ir_config_editable(self, client):
        """参数配置可视化编辑（经通用 CRUD 改 value 生效）。"""
        r = client.get("/api/v1/data/ir_config", params={"limit": 500})
        items = r.json()["records"]
        assert len(items) >= 1
        row = items[0]
        old = row.get("value")
        r2 = client.put(f"/api/v1/data/ir_config/{row['id']}",
                        json={"values": {"value": old}})
        assert r2.status_code == 200
