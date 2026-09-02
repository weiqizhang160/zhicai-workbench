# -*- coding: utf-8 -*-
"""M5 测试：合同收费 + 任务看板 + 仪表盘（项目书 7.2 / 7.4 DoD）。

DoD 对照（7.4）：
- 自动生成收费计划**不重复不遗漏**（幂等）
- **逾期判定**（today > due_date 且 unpaid）正确
DoD 对照（7.2）：
- 仪表盘**总览模式跨账套聚合正确**
"""
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


@contextmanager
def _new_env():
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"login": "admin", "password": "admin123"})
        assert r.status_code == 200
        uid = uuid.uuid4().hex[:8]
        r = c.post("/api/v1/biz/books", json={
            "name": f"M5测试公司{uid}", "short_name": f"M5{uid}",
            "credit_no": f"91{uid}M5X", "taxpayer_type": "small",
            "accounting_standard": "small",
        })
        assert r.status_code == 200, r.text
        book_id = r.json()["book"]["id"]
        c.put(f"/api/v1/biz/books/{book_id}/switch")
        yield {"c": c, "book_id": book_id, "uid": uid}


@pytest.fixture(scope="module")
def env():
    with _new_env() as e:
        yield e


def _mk_agreement(env, **kw):
    body = {"start_date": "2026-01-01", "end_date": "2026-12-31",
            "fee_type": "monthly", "fee_amount": "300"}
    body.update(kw)
    return env["c"].post("/api/v1/contract/agreements", json=body)


def _fee_items(env, book_id=None):
    p = {"book_id": book_id or env["book_id"], "limit": 2000}
    return env["c"].get("/api/v1/contract/fee-items", params=p).json()["items"]


# ==================== 合同与编号 ====================

class TestAgreement:

    def test_create_with_sequence(self, env):
        r = _mk_agreement(env)
        assert r.status_code == 200, r.text
        ag = r.json()["agreement"]
        assert ag["contract_no"].startswith("HT"), ag["contract_no"]
        assert ag["state"] == "active"
        assert Decimal(ag["fee_amount"]) == Decimal("300")

    def test_book_required_in_overview(self):
        """总览模式（未切账套）新建合同需显式 book_id 或切账套。"""
        from app.main import app
        with TestClient(app) as c:
            c.post("/api/v1/auth/login", json={"login": "admin", "password": "admin123"})
            c.put("/api/v1/biz/books/0/switch")  # 切到总览
            r = c.post("/api/v1/contract/agreements", json={
                "start_date": "2026-01-01", "end_date": "2026-12-31",
                "fee_type": "monthly", "fee_amount": "300"})
            assert r.status_code == 400
            assert r.json()["code"] == "book_required"


# ==================== 收费计划生成（幂等） ====================

class TestFeeGeneration:

    def test_monthly_12_periods(self, env):
        r = _mk_agreement(env, fee_type="monthly")
        assert r.json()["fee"]["created"] == 12, r.json()["fee"]
        items = _fee_items(env)
        periods = {i["period"] for i in items if i["agreement_id"] == r.json()["agreement"]["id"]}
        assert len(periods) == 12
        assert "2026-01" in periods and "2026-12" in periods

    def test_quarterly_4_periods(self, env):
        r = _mk_agreement(env, fee_type="quarterly")
        assert r.json()["fee"]["created"] == 4, r.json()["fee"]
        items = _fee_items(env)
        periods = {i["period"] for i in items if i["agreement_id"] == r.json()["agreement"]["id"]}
        assert periods == {"2026Q1", "2026Q2", "2026Q3", "2026Q4"}, periods

    def test_annual_1_period(self, env):
        r = _mk_agreement(env, fee_type="annual")
        assert r.json()["fee"]["created"] == 1, r.json()["fee"]

    def test_idempotent_regenerate(self, env):
        """重复生成不重复不遗漏。"""
        r = _mk_agreement(env, fee_type="monthly")
        ag_id = r.json()["agreement"]["id"]
        r2 = env["c"].post(f"/api/v1/contract/agreements/{ag_id}/fee-items/generate")
        assert r2.status_code == 200
        assert r2.json()["created"] == 0
        assert r2.json()["skipped"] == 12


# ==================== 逾期判定 ====================

class TestOverdue:

    def test_overdue_flag(self):
        """today > due_date 且未收 → overdue=True；paid → False。"""
        from app.modules.contract.models import ContractFeeItem
        item = ContractFeeItem(period="2026-01", amount=300, due_date=date(2026, 1, 1),
                               state="unpaid")
        assert item.is_overdue is True
        item.state = "paid"
        assert item.is_overdue is False

    def test_scan_marks_overdue_and_creates_task(self, env):
        """扫描：把过期未收的标 overdue 并生成催收任务。"""
        # 合同开始于 3 个月前，前几个月的期已到期未收
        today = date.today()
        start = (today - timedelta(days=120)).replace(day=1)
        r = _mk_agreement(env, start_date=start.isoformat(),
                          end_date=(today + timedelta(days=60)).isoformat(),
                          fee_type="monthly", fee_amount="500")
        ag_id = r.json()["agreement"]["id"]
        r2 = env["c"].post("/api/v1/contract/scan")
        assert r2.status_code == 200, r2.text
        assert r2.json()["overdue_marked"] > 0
        assert r2.json()["collection_tasks"] > 0

        # 重复扫描幂等：不再重复生成催收任务
        r3 = env["c"].post("/api/v1/contract/scan")
        assert r3.json()["collection_tasks"] == 0

        items = _fee_items(env)
        ag_items = [i for i in items if i["agreement_id"] == ag_id]
        assert any(i["state"] == "overdue" for i in ag_items)

    def test_renewal_task_within_30_days(self, env):
        """到期前 30 天内 → 生成续约提醒任务。"""
        today = date.today()
        r = _mk_agreement(env, start_date=(today - timedelta(days=300)).isoformat(),
                          end_date=(today + timedelta(days=20)).isoformat(),
                          fee_type="annual", fee_amount="1200")
        ag_id = r.json()["agreement"]["id"]
        r2 = env["c"].post("/api/v1/contract/scan")
        assert r2.status_code == 200
        assert r2.json()["renewal_tasks"] >= 1

        tasks = env["c"].get("/api/v1/tasks").json()["items"]
        renew = [t for t in tasks if t["source_model"] == "contract_agreement"
                 and t["source_id"] == ag_id]
        assert renew, "应生成续约提醒任务"


# ==================== 收款登记 ====================

class TestCollect:

    def test_bulk_collect(self, env):
        r = _mk_agreement(env, fee_type="monthly", fee_amount="300")
        ag_id = r.json()["agreement"]["id"]
        items = [i for i in _fee_items(env) if i["agreement_id"] == ag_id]
        ids = [i["id"] for i in items[:3]]
        r2 = env["c"].post("/api/v1/contract/fee-items/bulk-collect",
                           json={"fee_item_ids": ids, "paid_date": "2026-03-01"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["collected"] == 3

        # 重复收款：已收的不再计入
        r3 = env["c"].post("/api/v1/contract/fee-items/bulk-collect",
                           json={"fee_item_ids": ids})
        assert r3.json()["collected"] == 0

    def test_single_collect_and_invoice(self, env):
        r = _mk_agreement(env, fee_type="monthly", fee_amount="300")
        ag_id = r.json()["agreement"]["id"]
        it = [i for i in _fee_items(env) if i["agreement_id"] == ag_id][0]
        # 开票
        r2 = env["c"].post(f"/api/v1/contract/fee-items/{it['id']}/invoice",
                           json={"invoice_no": "INV001"})
        assert r2.json()["item"]["state"] == "invoiced"
        # 收款
        r3 = env["c"].post(f"/api/v1/contract/fee-items/{it['id']}/collect", json={})
        assert r3.json()["item"]["state"] == "paid"

    def test_receivable_report(self, env):
        _mk_agreement(env, fee_type="monthly", fee_amount="300")
        rep = env["c"].get("/api/v1/contract/report/receivable").json()
        assert "by_book" in rep and "by_month" in rep and "year_received" in rep
        # 本账套应收 = 12 × 300
        row = next(x for x in rep["by_book"] if x["book_id"] == env["book_id"])
        assert Decimal(row["receivable"]) >= Decimal("3600")


# ==================== 任务看板 ====================

class TestTasks:

    def test_create_and_state_flow(self, env):
        c = env["c"]
        r = c.post("/api/v1/tasks", json={"title": "测试任务", "priority": "high",
                                          "due_date": "2026-09-10"})
        assert r.status_code == 200, r.text
        tid = r.json()["task"]["id"]
        assert r.json()["task"]["state"] == "todo"
        assert r.json()["task"]["book_id"] == env["book_id"]

        r2 = c.post(f"/api/v1/tasks/{tid}/state", json={"state": "doing"})
        assert r2.json()["task"]["state"] == "doing"
        r3 = c.post(f"/api/v1/tasks/{tid}/state", json={"state": "done"})
        assert r3.json()["task"]["state"] == "done"

    def test_global_task(self, env):
        """总览模式下可建全局任务（book_id 空）。"""
        c = env["c"]
        c.put("/api/v1/biz/books/0/switch")
        r = c.post("/api/v1/tasks", json={"title": "全局任务"})
        assert r.status_code == 200, r.text
        assert r.json()["task"]["book_id"] is None
        c.put(f"/api/v1/biz/books/{env['book_id']}/switch")

    def test_kanban(self, env):
        r = env["c"].get("/api/v1/tasks/kanban")
        assert r.status_code == 200
        cols = {x["state"]: x["items"] for x in r.json()["columns"]}
        assert set(cols.keys()) == {"todo", "doing", "done", "cancelled"}

    def test_invalid_state_rejected(self, env):
        c = env["c"]
        r = c.post("/api/v1/tasks", json={"title": "x"})
        tid = r.json()["task"]["id"]
        r2 = c.post(f"/api/v1/tasks/{tid}/state", json={"state": "bogus"})
        assert r2.status_code == 400
        assert r2.json()["code"] == "state_invalid"


# ==================== 仪表盘 ====================

class TestDashboard:

    def test_summary_aggregates(self, env):
        r = _mk_agreement(env, fee_type="monthly", fee_amount="300")
        d = env["c"].get("/api/v1/dashboard/summary",
                         params={"month": "2026-01"}).json()
        assert d["overview"]["total_books"] >= 1
        assert d["overview"]["normal_books"] >= 1
        # 本月应收 = 本账套 1 期 300（+ 其他测试账套可能也有）
        assert Decimal(d["fee_month"]["receivable"]) >= Decimal("300")
        assert "progress" in d and len(d["progress"]) >= 1
        # 每个客户进度含四状态灯
        p = d["progress"][0]
        for key in ("invoice", "move", "decl", "fee"):
            assert "light" in p[key]

    def test_todo_tasks_in_dashboard(self, env):
        # 手动建的 urgent 任务应排在最前，出现在「待办任务」前 10 条里
        # （自动扫描生成的催收/续约任务为 high，不会淹没 urgent 手工任务）
        env["c"].post("/api/v1/tasks", json={"title": "仪表盘任务", "priority": "urgent"})
        d = env["c"].get("/api/v1/dashboard/summary").json()
        titles = [t["title"] for t in d["todo_tasks"]]
        assert "仪表盘任务" in titles
        assert all(t["state"] in ("todo", "doing") for t in d["todo_tasks"])
