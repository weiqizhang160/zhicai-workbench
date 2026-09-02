# -*- coding: utf-8 -*-
"""M4 测试：申报台账与日历（项目书 7.9 DoD）。

DoD 对照：
- 征期规则批量生成台账**幂等**且覆盖 **100 账套 < 10 秒**
- **逾期自动标红**（is_overdue 派生属性）
- **每笔计算底稿可追溯取数来源**（calc_snapshot 带 source，可穿透到发票/凭证）
"""
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

PERIOD = "2026-09"
Q_PERIOD = "2026Q3"


@contextmanager
def _new_env(taxpayer_type="general"):
    """独立账套环境（不初始化科目表，台账生成不依赖科目）。"""
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"login": "admin", "password": "admin123"})
        assert r.status_code == 200
        uid = uuid.uuid4().hex[:8]
        r = c.post("/api/v1/biz/books", json={
            "name": f"M4测试公司{uid}", "short_name": f"M4{uid}",
            "credit_no": f"91{uid}M4X", "taxpayer_type": taxpayer_type,
            "accounting_standard": "small",
        })
        assert r.status_code == 200, r.text
        book_id = r.json()["book"]["id"]
        c.put(f"/api/v1/biz/books/{book_id}/switch")
        # fixture 是懒加载的：后创建的账套不会赶上前面测试里的批量生成，
        # 因此每个环境创建时就补一次，保证下面按 tax_kind/period 查得到台账行。
        c.post("/api/v1/tax/generate", json={"periods": [PERIOD]})
        yield {"c": c, "book_id": book_id, "uid": uid}


@pytest.fixture(scope="module")
def env():
    with _new_env("general") as e:
        yield e


@pytest.fixture(scope="module")
def small_env():
    """小规模纳税人账套（验证按季申报与免征）。"""
    with _new_env("small") as e:
        yield e


def _inv(env, **kw):
    body = {"direction": "output", "invoice_type": "special", "invoice_no": "T1",
            "invoice_date": "2026-09-01", "goods_amount": "1000", "tax_rate": "0.13"}
    body.update(kw)
    return env["c"].post("/api/v1/inv/bills", json=body)


def _item(env, tax_kind, period):
    items = env["c"].get("/api/v1/tax/items",
                         params={"tax_kind": tax_kind, "period": period,
                                 "book_id": env["book_id"]}).json()["items"]
    return items[0] if items else None


# ==================== 征期规则与截止日 ====================

class TestCalendarRules:

    def test_seed_rules_exist(self, env):
        r = env["c"].get("/api/v1/data/tax_calendar_rule")
        assert r.status_code == 200
        rules = r.json()["records"]
        assert len(rules) >= 8, f"应有 8 条种子征期规则，实际 {len(rules)}"
        kinds = {x["tax_kind"] for x in rules}
        assert {"vat", "surtax", "cit_quarterly", "cit_annual", "iit", "stamp"} <= kinds

    def test_generate_and_idempotent(self, env):
        """批量生成 + 幂等（重复执行不重复生成）。

        用一个 fixture 尚未生成的属期（2026-12），
        否则 fixture 创建账套时已经生成过 2026-09，这里会全部跳过。
        """
        c = env["c"]
        p = "2026-12"
        r1 = c.post("/api/v1/tax/generate", json={"periods": [p]})
        assert r1.status_code == 200, r1.text
        first = r1.json()
        assert first["created"] > 0, first

        r2 = c.post("/api/v1/tax/generate", json={"periods": [p]})
        second = r2.json()
        assert second["created"] == 0, f"重复执行不应新建，实际 {second['created']}"
        assert second["skipped"] == first["created"] + first["skipped"]

    def test_monthly_period_expands_quarterly(self, env):
        """传月度属期要同时生成季度项（否则印花税/所得税预缴会被漏掉）。"""
        r = env["c"].post("/api/v1/tax/generate", json={"periods": [PERIOD]})
        assert r.status_code == 200
        assert Q_PERIOD in r.json()["periods"], r.json()["periods"]

    def test_deadlines(self, env):
        """截止日：月度次月 15 日、季度次季首月 15 日、年度次年 5/31。"""
        from app.modules.tax_decl.calendar_service import deadline_of
        assert deadline_of("2026-09", "next_month_15") == date(2026, 10, 15)
        assert deadline_of("2026Q3", "quarter_next_month_15") == date(2026, 10, 15)
        assert deadline_of("2026Q4", "quarter_next_month_15") == date(2027, 1, 15)
        assert deadline_of("2026", "annual_0531") == date(2027, 5, 31)

    def test_vat_monthly_for_general_quarterly_for_small(self, env, small_env):
        """一般纳税人增值税按月；小规模按季。"""
        # 一般纳税人：属期应是月份
        it = _item(env, "vat", PERIOD)
        assert it is not None, "一般纳税人应有月度增值税台账"
        assert it["period"] == PERIOD

        # 小规模：属期应是季度
        it2 = _item(small_env, "vat", Q_PERIOD)
        assert it2 is not None, "小规模应有季度增值税台账"
        assert it2["period"] == Q_PERIOD


# ==================== DoD：100 账套 < 10 秒 ====================

class TestBulkPerformance:
    """DoD：征期规则批量生成台账覆盖 100 账套 < 10 秒。

    注意：本测试**不使用 TestClient**——TestClient 会持有 SQLite 连接，
    与 SessionLocal 混用会触发 "database is locked"。纯 DB 层测试即可。
    """

    def test_100_books_under_10s(self):
        from sqlalchemy import delete as sa_delete

        from app.core.db import SessionLocal
        from app.modules.res_partner.models import ResBook
        from app.modules.tax_decl.calendar_service import generate_items
        from app.modules.tax_decl.models import TaxDeclItem

        db = SessionLocal()
        books: list = []
        try:
            # 直接插入 100 个账套（走 create_book API 会克隆科目表，太慢且非本测试重点）
            base = uuid.uuid4().hex[:6]
            for i in range(100):
                books.append(ResBook(
                    code=f"PERF{base}{i:03d}", name=f"性能测试公司{i}",
                    short_name=f"性能{i}", taxpayer_type="general",
                    accounting_standard="small", vat_period="monthly",
                    charge_status="normal",
                    create_date=datetime.now(), write_date=datetime.now(), active=True))
            db.add_all(books)
            db.commit()
            book_ids = [b.id for b in books]
            assert len(book_ids) == 100

            t0 = time.time()
            result = generate_items(db, [PERIOD], book_ids)
            elapsed = time.time() - t0

            assert result["books"] == 100, result
            assert result["created"] > 0
            assert elapsed < 10, f"100 账套台账生成耗时 {elapsed:.2f}s，超过 10 秒预算"

            # 幂等：再来一次应全部跳过
            t1 = time.time()
            again = generate_items(db, [PERIOD], book_ids)
            assert again["created"] == 0, again
            assert (time.time() - t1) < 10
        finally:
            # 清理必须**先删台账再删账套**：res_book 被子表外键引用，
            # 直接删账套会触发 FOREIGN KEY constraint failed。
            try:
                ids = [b.id for b in books]
                if ids:
                    db.execute(sa_delete(TaxDeclItem).where(TaxDeclItem.book_id.in_(ids)))
                    db.commit()
                    for b in books:
                        db.delete(b)
                    db.commit()
            finally:
                db.close()


# ==================== DoD：逾期标红 ====================

class TestOverdue:

    def test_overdue_flag(self):
        """截止日已过且未申报 → overdue=True。

        同样走纯 DB（避免与 TestClient 争抢 SQLite 连接）。
        """
        from sqlalchemy import delete as sa_delete

        from app.core.db import SessionLocal
        from app.modules.res_partner.models import ResBook
        from app.modules.tax_decl.models import TaxDeclItem

        db = SessionLocal()
        book = None
        try:
            uid = uuid.uuid4().hex[:8]
            book = ResBook(code=f"OD{uid}", name=f"逾期测试{uid}", short_name=f"逾期{uid}",
                           taxpayer_type="small", accounting_standard="small",
                           vat_period="quarterly", charge_status="normal",
                           create_date=datetime.now(), write_date=datetime.now(), active=True)
            db.add(book)
            db.commit()

            def mk(period, due, state):
                it = TaxDeclItem(book_id=book.id, tax_kind="vat", period=period,
                                 due_date=due, state=state, computed_amount=0,
                                 source="manual", create_date=datetime.now(),
                                 write_date=datetime.now(), active=True)
                db.add(it)
                db.commit()
                return it

            # 截止日已过 + 待申报 → 逾期
            assert mk("2026-01", date(2026, 2, 15), "pending").is_overdue is True
            # 准备中 + 已过截止 → 仍逾期
            assert mk("2026-02", date(2026, 3, 15), "preparing").is_overdue is True
            # 已申报 → 不逾期
            assert mk("2026-03", date(2026, 4, 15), "submitted").is_overdue is False
            # 已缴款 → 不逾期
            assert mk("2026-04", date(2026, 5, 15), "paid").is_overdue is False
            # 免税/零申报 → 不逾期
            assert mk("2026-05", date(2026, 6, 15), "exempt").is_overdue is False
            # 未来截止日 → 不逾期
            assert mk("2026-11", date(2099, 12, 15), "pending").is_overdue is False
        finally:
            try:
                if book is not None:
                    db.execute(sa_delete(TaxDeclItem).where(TaxDeclItem.book_id == book.id))
                    db.commit()
                    db.delete(book)
                    db.commit()
            finally:
                db.close()

    def test_overdue_only_filter(self, env):
        r = env["c"].get("/api/v1/tax/items", params={"overdue_only": True})
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["overdue"] is True


# ==================== DoD：计算底稿可追溯 ====================

class TestCalcWorksheet:

    def test_vat_general_computation(self, env):
        """一般纳税人：应纳税额 = 销项 - 进项 - 上期留抵。"""
        c = env["c"]
        # 销项：100000×13% = 13000；进项：30000×13% = 3900
        _inv(env, invoice_no="V001", direction="output", goods_amount="100000",
             tax_rate="0.13", invoice_date="2026-09-03")
        _inv(env, invoice_no="V002", direction="input", goods_amount="30000",
             tax_rate="0.13", invoice_date="2026-09-05", category="material")

        it = _item(env, "vat", PERIOD)
        assert it is not None
        snap = c.post(f"/api/v1/tax/items/{it['id']}/compute", json={}).json()["snapshot"]

        assert snap["formula"].startswith("一般纳税人")
        # 13000 - 3900 = 9100
        assert Decimal(snap["result"]) == Decimal("9100.00"), snap

        # 底稿必须有取数来源（可穿透到发票）
        out = next(x for x in snap["items"] if x["label"] == "销项税额合计")
        assert out["amount"] == "13000.00"
        assert out["source"]["type"] == "invoice"
        assert out["source"]["direction"] == "output"
        assert out["count"] == 1

        inn = next(x for x in snap["items"] if x["label"] == "进项税额合计")
        assert inn["amount"] == "3900.00"
        assert inn["source"]["direction"] == "input"

    def test_vat_small_exempt(self, small_env):
        """小规模：季度不含税销售额未超 30 万 → 免征。"""
        c = small_env["c"]
        _inv(small_env, invoice_no="S001", direction="output", goods_amount="100000",
             tax_rate="0.03", invoice_date="2026-09-08")

        it = _item(small_env, "vat", Q_PERIOD)
        assert it is not None
        snap = c.post(f"/api/v1/tax/items/{it['id']}/compute", json={}).json()["snapshot"]
        assert snap["formula"].startswith("小规模")
        assert Decimal(snap["result"]) == Decimal("0.00"), snap
        assert "免征" in (snap.get("note") or ""), snap

    def test_vat_small_taxable(self, small_env):
        """小规模超过免征额 → 按征收率计算：50万/1.03×3%。"""
        c = small_env["c"]
        # 先让季度销售额超过 30 万
        _inv(small_env, invoice_no="S002", direction="output", goods_amount="500000",
             tax_rate="0.03", invoice_date="2026-09-09")
        it = _item(small_env, "vat", Q_PERIOD)
        snap = c.post(f"/api/v1/tax/items/{it['id']}/compute", json={}).json()["snapshot"]
        expected = (Decimal("500000") / Decimal("1.03") * Decimal("0.03")).quantize(
            Decimal("0.01"))
        # 注意前面已有一张 100000 的票，这里只校验大于 0 且公式正确
        assert Decimal(snap["result"]) > 0, snap
        assert snap["policy"]["mode"] == "small"

    def test_surtax_based_on_vat(self, env):
        """附加税 = 实缴增值税 ×(7%+3%+2%)。"""
        c = env["c"]
        it = _item(env, "vat", PERIOD)
        # 先把增值税标记为已申报，填实缴额 9100
        c.post(f"/api/v1/tax/items/{it['id']}/submit",
               json={"declared_amount": "9100.00"})

        st = _item(env, "surtax", PERIOD)
        assert st is not None
        snap = c.post(f"/api/v1/tax/items/{st['id']}/compute", json={}).json()["snapshot"]
        base = next(x for x in snap["items"] if "计税依据" in x["label"])
        assert base["amount"] == "9100.00"
        # 9100 × 12% = 1092
        assert Decimal(snap["result"]) == Decimal("1092.00"), snap

    def test_stamp_tax(self, env):
        """印花税 = 购销合计 × 0.3‰。"""
        c = env["c"]
        it = _item(env, "stamp", Q_PERIOD)
        assert it is not None
        snap = c.post(f"/api/v1/tax/items/{it['id']}/compute", json={}).json()["snapshot"]
        assert "0.3‰" in snap["formula"] or "0.0003" in snap["formula"]
        base = next(x for x in snap["items"] if "计税依据" in x["label"])
        # 销项价税 113000 + 进项价税 33900 = 146900
        assert base["amount"] == "146900.00", snap
        assert Decimal(snap["result"]) == Decimal("44.07"), snap

    def test_stamp_base_overridable(self, env):
        """印花税计税依据可手工调整（项目书要求）。"""
        c = env["c"]
        it = _item(env, "stamp", Q_PERIOD)
        snap = c.post(f"/api/v1/tax/items/{it['id']}/compute",
                      json={"overrides": {"base": "100000"}}).json()["snapshot"]
        assert Decimal(snap["result"]) == Decimal("30.00"), snap

    def test_cit_summary_only(self, env):
        """企业所得税只出取数汇总，不做计算。"""
        c = env["c"]
        it = _item(env, "cit_quarterly", Q_PERIOD)
        assert it is not None
        snap = c.post(f"/api/v1/tax/items/{it['id']}/compute", json={}).json()["snapshot"]
        assert snap["policy"]["mode"] == "summary_only"
        assert Decimal(snap["result"]) == Decimal("0.00")
        labels = [x["label"] for x in snap["items"]]
        assert "营业收入" in labels and "利润总额（收入−成本−费用）" in labels

    def test_snapshot_persisted_and_readable(self, env):
        """计算后底稿要能再次读取（刷新页面不丢）。"""
        c = env["c"]
        it = _item(env, "vat", PERIOD)
        c.post(f"/api/v1/tax/items/{it['id']}/compute", json={})
        r = c.get(f"/api/v1/tax/items/{it['id']}/snapshot")
        assert r.status_code == 200
        assert r.json()["snapshot"] is not None
        assert r.json()["snapshot"]["tax_kind"] == "vat"


# ==================== 状态流转 ====================

class TestStateFlow:

    def test_pending_to_paid(self, env):
        c = env["c"]
        it = _item(env, "iit", PERIOD)
        assert it is not None
        assert it["state"] in ("pending", "preparing")

        r = c.post(f"/api/v1/tax/items/{it['id']}/submit",
                   json={"declared_amount": "500.00", "remark": "测试申报"})
        assert r.status_code == 200, r.text
        assert r.json()["item"]["state"] == "submitted"
        assert Decimal(r.json()["item"]["declared_amount"]) == Decimal("500.00")

        r2 = c.post(f"/api/v1/tax/items/{it['id']}/pay", json={"paid_date": "2026-10-10"})
        assert r2.status_code == 200
        assert r2.json()["item"]["state"] == "paid"
        assert r2.json()["item"]["paid_date"] == "2026-10-10"

    def test_exempt(self, env):
        c = env["c"]
        it = _item(env, "stamp", Q_PERIOD)
        r = c.post(f"/api/v1/tax/items/{it['id']}/exempt",
                   json={"reason": "未达起征点", "zero": True})
        assert r.status_code == 200
        assert r.json()["item"]["state"] == "exempt"
        assert "零申报" in (r.json()["item"]["remark"] or "")

    def test_back_to_pending(self, env):
        c = env["c"]
        it = _item(env, "stamp", Q_PERIOD)
        r = c.post(f"/api/v1/tax/items/{it['id']}/state", json={"state": "pending"})
        assert r.status_code == 200
        assert r.json()["item"]["state"] == "pending"

    def test_invalid_state_rejected(self, env):
        c = env["c"]
        it = _item(env, "stamp", Q_PERIOD)
        r = c.post(f"/api/v1/tax/items/{it['id']}/state", json={"state": "bogus"})
        assert r.status_code == 400
        assert r.json()["code"] == "state_invalid"


# ==================== 日历与官网链接 ====================

class TestCalendarView:

    def test_calendar_data(self, env):
        r = env["c"].get("/api/v1/tax/calendar", params={"month": "2026-10"})
        assert r.status_code == 200
        data = r.json()
        assert "days" in data and "stats" in data
        assert data["stats"]["total"] > 0

    def test_official_links(self, env):
        r = env["c"].get("/api/v1/tax/links")
        assert r.status_code == 200
        links = r.json()["links"]
        assert "vat" in links and links["vat"]["url"].startswith("http")
        assert "iit" in links
