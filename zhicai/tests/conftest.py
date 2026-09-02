# -*- coding: utf-8 -*-
"""pytest 共享夹具：独立临时数据库 + 已登录的 TestClient。"""
import os
import tempfile
from pathlib import Path

# 必须在 import app 之前设置：让 db engine 指向临时库
_TMP_DIR = tempfile.mkdtemp(prefix="zhicai-test-")
os.environ["ZC_DB_PATH"] = str(Path(_TMP_DIR) / "test.db")
# 关闭后台计划任务线程（测试里手动触发 cron，不让调度器抢跑）
os.environ["ZC_DISABLE_SCHEDULER"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """会话级客户端：启动应用（建表+种子）并登录 admin。"""
    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"login": "admin", "password": "admin123"})
        assert r.status_code == 200, "admin 登录失败"
        yield c


@pytest.fixture()
def fresh_client():
    """未登录的干净客户端（验证 401 拦截用）。"""
    from app.main import app
    with TestClient(app) as c:
        yield c
