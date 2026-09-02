# -*- coding: utf-8 -*-
"""M2 记账核心测试：过账校验 / 红冲 / 期间锁 / 结转 / 账簿 / 报表（项目书 7.5 DoD ①-④）。

业务场景（构造一套能自平衡的真实账）：
  000 投资：借 银行存款 50000 / 贷 实收资本 50000
  001 销售：借 应收账款 11300 / 贷 主营业务收入 10000 + 销项税额 1300
  002 费用：借 办公费 500 / 贷 银行存款 500
  003 提现：借 库存现金 1000 / 贷 银行存款 1000
  => 资产 60800 = 负债 1300 + 权益 59500（3001 实收资本 50000 + 3103 本年利润 9500）
  => 净利润 9500 = 本年利润科目发生额
"""
import uuid
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

PERIOD = "2026-09"
DATE = "2026-09-10"


# ==================== 夹具 ====================

@contextmanager
def _new_env():
    """新建一个独立账套环境（含往来单位），避免测试间数据互相污染。"""
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"login": "admin", "password": "admin123"})
        assert r.status_code == 200

        # 新建独立账套（向导自动克隆科目表 + 账簿 + 编号器）
        uid = uuid.uuid4().hex[:8]
        r = c.post("/api/v1/biz/books", json={
            "name": f"M2测试公司{uid}", "short_name": f"M2测试{uid}",
            "credit_no": f"91{uid}XM2", "taxpayer_type": "small",
            "accounting_standard": "small",
        })
        assert r.status_code == 200, r.text
        book_id = r.json()["book"]["id"]
        c.put(f"/api/v1/biz/books/{book_id}/switch")

        # 往来单位（6001 / 1122 启用了 partner 辅助核算）
        r = c.post("/api/v1/data/res_partner",
                   json={"values": {"name": "M2测试客户", "partner_type": "customer"}})
        assert r.status_code == 200, r.text
        partner_id = r.json()["record"]["id"]

        yield {"c": c, "book_id": book_id, "partner_id": partner_id, "uid": uid}


@pytest.fixture(scope="module")
def env():
    """约束校验 / 红冲 / 期间锁测试用账套（允许残留脏数据）。"""
    with _new_env() as e:
        yield e


@pytest.fixture(scope="module")
def biz_env():
    """干净业务账套：完整账务周期 → 账簿 → 列表，要求数据不被前面的测试污染。"""
    with _new_env() as e:
        yield e


def _acc(env, code: str) -> int:
    """按编码查科目 id（含非末级）。"""
    import json as _json
    r = env["c"].get("/api/v1/data/account_account",
                     params={"domain": _json.dumps([["code", "=", code]])})
    assert r.status_code == 200, r.text
    rows = r.json()["records"]
    assert rows, f"科目 {code} 不存在"
    return rows[0]["id"]


def _leaf(env, code: str) -> int:
    """查末级科目 id（科目联想只出末级）。"""
    r = env["c"].get("/api/v1/acc/accounts/leaf", params={"kw": code})
    assert r.status_code == 200, r.text
    for a in r.json()["accounts"]:
        if a["code"] == code:
            return a["id"]
    raise AssertionError(f"末级科目 {code} 不存在")


def _moves(env):
    return env["c"].get("/api/v1/acc/moves").json()


def _mk(env, lines, date=DATE, **kw):
    """建一张草稿凭证。"""
    body = {"journal_id": kw.get("journal_id", 1), "move_date": date, "lines": lines}
    body.update({k: v for k, v in kw.items() if k != "journal_id"})
    r = env["c"].post("/api/v1/acc/moves", json=body)
    assert r.status_code == 200, r.text
    return r.json()["move"]["id"]


def _post(env, mid):
    return env["c"].post(f"/api/v1/acc/moves/{mid}/post")


def _journal(env, code="记") -> int:
    r = env["c"].get("/api/v1/acc/journals")
    for j in r.json()["journals"]:
        if j["code"] == code:
            return j["id"]
    raise AssertionError(f"凭证字 {code} 不存在")


# ==================== DoD ①：过账校验每个约束分支 ====================

class TestPostValidation:
    """项目书 6.5 约束：过账前必须全通过。"""

    def test_unbalanced_rejected(self, env):
        """借贷不平衡 → 拦截。"""
        mid = _mk(env, [
            {"summary": "测试", "account_id": _leaf(env, "1001"), "debit": "100.00", "credit": "0"},
            {"summary": "测试", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "50.00"},
        ])
        r = _post(env, mid)
        assert r.status_code == 400
        assert r.json()["code"] == "move_unbalanced"
        assert "差额" in r.json()["message"]

    def test_zero_amount_rejected(self, env):
        """借贷均为 0 → 拦截（金额必须 > 0）。"""
        mid = _mk(env, [
            {"summary": "测试", "account_id": _leaf(env, "1001"), "debit": "0", "credit": "0"},
            {"summary": "测试", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "0"},
        ])
        r = _post(env, mid)
        assert r.status_code == 400
        assert r.json()["code"] == "amount_empty"

    def test_less_than_two_lines_rejected(self, env):
        """行数 < 2 → 拦截。"""
        mid = _mk(env, [
            {"summary": "只有一行", "account_id": _leaf(env, "1001"), "debit": "0", "credit": "0"},
        ])
        r = _post(env, mid)
        assert r.status_code == 400
        assert r.json()["code"] == "move_lines_min"

    def test_debit_credit_exclusive(self, env):
        """同一行借贷同时有金额 → 拦截。"""
        mid = _mk(env, [
            {"summary": "双向金额", "account_id": _leaf(env, "1001"), "debit": "100", "credit": "50"},
            {"summary": "双向金额", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "100"},
        ])
        r = _post(env, mid)
        assert r.status_code == 400
        assert r.json()["code"] == "amount_exclusive"

    def test_summary_required(self, env):
        """摘要为空 → 拦截（中国凭证要素）。"""
        mid = _mk(env, [
            {"summary": "  ", "account_id": _leaf(env, "1001"), "debit": "100", "credit": "0"},
            {"summary": "测试", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "100"},
        ])
        r = _post(env, mid)
        assert r.status_code == 400
        assert r.json()["code"] == "summary_required"

    def test_account_required(self, env):
        """科目为空 → 拦截。"""
        mid = _mk(env, [
            {"summary": "无科目", "account_id": None, "debit": "100", "credit": "0"},
            {"summary": "无科目", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "100"},
        ])
        r = _post(env, mid)
        assert r.status_code == 400
        assert r.json()["code"] == "account_required"

    def test_non_leaf_account_rejected(self, env):
        """非末级科目（6602 管理费用有明细）→ 拦截。"""
        mid = _mk(env, [
            {"summary": "记到父科目", "account_id": _acc(env, "6602"), "debit": "100", "credit": "0"},
            {"summary": "记到父科目", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "100"},
        ])
        r = _post(env, mid)
        assert r.status_code == 400
        assert r.json()["code"] == "account_not_leaf"

    def test_partner_required_when_aux_enabled(self, env):
        """科目启用往来单位辅助核算（6001）但未填 → 拦截。"""
        mid = _mk(env, [
            {"summary": "无往来单位", "account_id": _leaf(env, "6001"), "debit": "0", "credit": "100"},
            {"summary": "无往来单位", "account_id": _leaf(env, "1002"), "debit": "100", "credit": "0"},
        ])
        r = _post(env, mid)
        assert r.status_code == 400
        assert r.json()["code"] == "partner_required"

    def test_double_post_rejected(self, env):
        """重复过账 → 拦截（已 posted 不是 draft）。"""
        mid = _mk(env, [
            {"summary": "正常凭证", "account_id": _leaf(env, "1001"), "debit": "10", "credit": "0"},
            {"summary": "正常凭证", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "10"},
        ])
        assert _post(env, mid).status_code == 200
        r = _post(env, mid)
        assert r.status_code == 400
        assert r.json()["code"] == "move_not_draft"

    def test_valid_move_posted_and_numbered(self, env):
        """合法凭证：过账成功 + 生成 记-YYYYMM-NNNN 格式凭证号。"""
        mid = _mk(env, [
            {"summary": "合规凭证", "account_id": _leaf(env, "1001"), "debit": "88.88", "credit": "0"},
            {"summary": "合规凭证", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "88.88"},
        ])
        r = _post(env, mid)
        assert r.status_code == 200, r.text
        move = r.json()["move"]
        assert move["state"] == "posted"
        assert move["name"].startswith("记-202609-")
        assert move["name"].split("-")[-1].isdigit()


# ==================== posted 只读 + 红冲 ====================

class TestPostedReadonlyAndReversal:

    def test_posted_move_readonly(self, env):
        """posted 后整单只读：不能改、不能删。"""
        mid = _mk(env, [
            {"summary": "只读验证", "account_id": _leaf(env, "1001"), "debit": "20", "credit": "0"},
            {"summary": "只读验证", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "20"},
        ])
        _post(env, mid)
        r = env["c"].put(f"/api/v1/acc/moves/{mid}", json={
            "journal_id": _journal(env), "move_date": DATE,
            "lines": [{"summary": "改摘要", "account_id": _leaf(env, "1001"),
                       "debit": "30", "credit": "0"}]})
        assert r.status_code == 400
        assert r.json()["code"] == "move_readonly"

        r = env["c"].delete(f"/api/v1/acc/moves/{mid}")
        assert r.status_code == 400
        assert r.json()["code"] == "move_readonly"

    def test_draft_editable_and_deletable(self, env):
        """draft 可任意编辑与删除。"""
        mid = _mk(env, [
            {"summary": "草稿", "account_id": _leaf(env, "1001"), "debit": "5", "credit": "0"},
            {"summary": "草稿", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "5"},
        ])
        r = env["c"].put(f"/api/v1/acc/moves/{mid}", json={
            "journal_id": _journal(env), "move_date": DATE,
            "lines": [
                {"summary": "改后", "account_id": _leaf(env, "1001"), "debit": "6", "credit": "0"},
                {"summary": "改后", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "6"},
            ]})
        assert r.status_code == 200, r.text
        assert r.json()["move"]["lines"][0]["summary"] == "改后"
        assert env["c"].delete(f"/api/v1/acc/moves/{mid}").status_code == 200

    def test_reverse_swaps_dr_cr_and_links(self, env):
        """红冲：借贷互换 + 摘要加"红冲：" + 两单互链 + 原单 voided。"""
        mid = _mk(env, [
            {"summary": "待红冲", "account_id": _leaf(env, "1001"), "debit": "300", "credit": "0"},
            {"summary": "待红冲", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "300"},
        ])
        _post(env, mid)

        r = env["c"].post(f"/api/v1/acc/moves/{mid}/reverse", json={})
        assert r.status_code == 200, r.text
        rev = r.json()["move"]

        # 借贷互换
        assert rev["lines"][0]["debit"] == "0.00" and rev["lines"][0]["credit"] == "300.00"
        assert rev["lines"][1]["debit"] == "300.00" and rev["lines"][1]["credit"] == "0.00"
        # 摘要前缀
        assert rev["lines"][0]["summary"] == "红冲：待红冲"
        # 来源标记
        assert rev["source_type"] == "reversal"
        assert rev["state"] == "posted"

        # 互链
        orig = env["c"].get(f"/api/v1/acc/moves/{mid}").json()["move"]
        assert orig["state"] == "voided"
        assert orig["reversed_move_id"] == rev["id"]
        assert rev["reversed_from_id"] == mid

    def test_reverse_twice_rejected(self, env):
        """同一张凭证不能红冲两次。"""
        mid = _mk(env, [
            {"summary": "防重复红冲", "account_id": _leaf(env, "1001"), "debit": "7", "credit": "0"},
            {"summary": "防重复红冲", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "7"},
        ])
        _post(env, mid)
        assert env["c"].post(f"/api/v1/acc/moves/{mid}/reverse", json={}).status_code == 200
        r = env["c"].post(f"/api/v1/acc/moves/{mid}/reverse", json={})
        assert r.status_code == 400
        assert r.json()["code"] == "already_reversed"

    def test_reverse_draft_rejected(self, env):
        """草稿不能红冲（必须先过账）。"""
        mid = _mk(env, [
            {"summary": "草稿红冲", "account_id": _leaf(env, "1001"), "debit": "3", "credit": "0"},
            {"summary": "草稿红冲", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "3"},
        ])
        r = env["c"].post(f"/api/v1/acc/moves/{mid}/reverse", json={})
        assert r.status_code == 400
        assert r.json()["code"] == "reverse_require_posted"


# ==================== 期间锁 ====================

class TestPeriodLock:

    def test_closed_period_blocks_new_move(self, env):
        """已结账期间禁止新增凭证。"""
        env["c"].post("/api/v1/acc/period/close", json={"period": "2026-01"})
        mid_try = env["c"].post("/api/v1/acc/moves", json={
            "journal_id": _journal(env), "move_date": "2026-01-15",
            "lines": [{"summary": "跨期补录", "account_id": _leaf(env, "1001"),
                       "debit": "1", "credit": "0"}]})
        assert mid_try.status_code == 400
        assert mid_try.json()["code"] == "period_closed"

    def test_reopen_allows_entry(self, env):
        """解锁后可以补录（并留审计）。"""
        env["c"].post("/api/v1/acc/period/open", json={"period": "2026-01"})
        r = env["c"].post("/api/v1/acc/moves", json={
            "journal_id": _journal(env), "move_date": "2026-01-15",
            "lines": [
                {"summary": "解锁后补录", "account_id": _leaf(env, "1001"), "debit": "1", "credit": "0"},
                {"summary": "解锁后补录", "account_id": _leaf(env, "1002"), "debit": "0", "credit": "1"},
            ]})
        assert r.status_code == 200, r.text

    def test_close_twice_rejected(self, env):
        env["c"].post("/api/v1/acc/period/close", json={"period": "2026-02"})
        r = env["c"].post("/api/v1/acc/period/close", json={"period": "2026-02"})
        assert r.status_code == 400
        assert r.json()["code"] == "period_already_closed"
        env["c"].post("/api/v1/acc/period/open", json={"period": "2026-02"})


# ==================== DoD ②③④：完整账务 + 结转 + 报表 ====================

class TestFullAccountingCycle:
    """构造真实账 → 过账 → 结转 → 验证余额表/资产负债表/利润表。"""

    def test_full_cycle(self, biz_env):
        c = biz_env["c"]
        jid = _journal(biz_env)
        pid = biz_env["partner_id"]

        # ---- 1. 录入 4 张凭证并过账 ----
        moves = [
            # 投资：借 银行存款 / 贷 实收资本
            [{"summary": "收到投资款", "account_id": _leaf(biz_env, "1002"), "debit": "50000", "credit": "0"},
             {"summary": "收到投资款", "account_id": _leaf(biz_env, "3001"), "debit": "0", "credit": "50000"}],
            # 销售：借 应收账款 / 贷 收入 + 销项税
            [{"summary": "销售商品", "account_id": _leaf(biz_env, "1122"), "debit": "11300", "credit": "0",
              "partner_id": pid},
             {"summary": "销售商品", "account_id": _leaf(biz_env, "6001"), "debit": "0", "credit": "10000",
              "partner_id": pid},
             {"summary": "销项税额", "account_id": _leaf(biz_env, "2221.01.01"), "debit": "0", "credit": "1300"}],
            # 费用：借 办公费 / 贷 银行存款
            [{"summary": "购买办公用品", "account_id": _leaf(biz_env, "6602.01"), "debit": "500", "credit": "0"},
             {"summary": "购买办公用品", "account_id": _leaf(biz_env, "1002"), "debit": "0", "credit": "500"}],
            # 提现：借 库存现金 / 贷 银行存款
            [{"summary": "提取现金", "account_id": _leaf(biz_env, "1001"), "debit": "1000", "credit": "0"},
             {"summary": "提取现金", "account_id": _leaf(biz_env, "1002"), "debit": "0", "credit": "1000"}],
        ]
        for lines in moves:
            mid = _mk(biz_env, lines)
            r = _post(biz_env, mid)
            assert r.status_code == 200, r.text

        # ---- 2. 结转前：利润表净利润 9500 ----
        pl = c.get("/api/v1/acc/report/income",
                   params={"period_from": PERIOD, "period_to": PERIOD}).json()
        assert pl["net_profit"] == "9500.00", pl
        # 尚未结转，本年利润科目无发生额 → 一致性校验应为 False 并给出提示
        assert pl["consistent"] is False
        assert pl["note"]

        # ---- 3. 期末结转 ----
        r = c.post("/api/v1/acc/carry-forward", json={"period": PERIOD})
        assert r.status_code == 200, r.text
        closing = r.json()["move"]
        assert closing["source_type"] == "closing"
        assert closing["state"] == "posted"
        assert closing["diff"] == "0.00"

        # ---- DoD ②：结转后损益科目余额为 0 ----
        tb = c.get("/api/v1/acc/ledger/trial",
                   params={"period_from": PERIOD, "period_to": PERIOD}).json()["rows"]
        by_code = {r["code"]: r for r in tb}
        for code in ("6001", "6602.01"):
            assert by_code[code]["ending"] == "0.00", f"{code} 结转后余额应为 0，实际 {by_code[code]}"

        # 本年利润 = 收入 10000 - 费用 500 = 9500（贷方，有符号为正）
        assert by_code["3103"]["ending"] == "9500.00", by_code.get("3103")

        # ---- DoD ③：资产负债表平衡 ----
        bs = c.get("/api/v1/acc/report/balance-sheet", params={"period": PERIOD}).json()
        assert bs["balanced"] is True, bs
        assert bs["diff"] == "0.00"
        assert bs["total_assets"] == "60800.00", bs["total_assets"]
        assert bs["total_liab_equity"] == "60800.00", bs["total_liab_equity"]
        assert bs["warning"] is None

        # ---- DoD ④：净利润 = 本年利润科目发生额 ----
        pl2 = c.get("/api/v1/acc/report/income",
                    params={"period_from": PERIOD, "period_to": PERIOD}).json()
        assert pl2["net_profit"] == "9500.00"
        assert pl2["profit_account_move"] == "9500.00"
        assert pl2["consistent"] is True, pl2
        assert pl2["note"] is None

    def test_carry_forward_twice_rejected(self, biz_env):
        """同期间重复结转 → 拦截。"""
        r = biz_env["c"].post("/api/v1/acc/carry-forward", json={"period": PERIOD})
        assert r.status_code == 400
        assert r.json()["code"] == "already_closed_period"

    def test_closing_period_locked_after_carry(self, biz_env):
        """结账后该期间不能新增凭证。"""
        biz_env["c"].post("/api/v1/acc/period/close", json={"period": PERIOD})
        r = biz_env["c"].post("/api/v1/acc/moves", json={
            "journal_id": _journal(biz_env), "move_date": DATE,
            "lines": [{"summary": "锁后新增", "account_id": _leaf(biz_env, "1001"),
                       "debit": "1", "credit": "0"}]})
        assert r.status_code == 400
        assert r.json()["code"] == "period_closed"
        biz_env["c"].post("/api/v1/acc/period/open", json={"period": PERIOD})


# ==================== 账簿查询 ====================

class TestLedger:

    def test_general_ledger(self, biz_env):
        rows = biz_env["c"].get("/api/v1/acc/ledger/general",
                            params={"period_from": PERIOD, "period_to": PERIOD}).json()["rows"]
        by_code = {r["code"]: r for r in rows}
        assert "1002" in by_code
        # 银行存款：本期借 50000，贷 1500，期末 48500
        assert by_code["1002"]["debit"] == "50000.00"
        assert by_code["1002"]["credit"] == "1500.00"
        assert by_code["1002"]["ending"] == "48500.00"

    def test_subsidiary_ledger(self, biz_env):
        acc_id = _leaf(biz_env, "1002")
        data = biz_env["c"].get("/api/v1/acc/ledger/subsidiary",
                            params={"account_id": acc_id, "period_from": PERIOD,
                                    "period_to": PERIOD}).json()
        assert data["account"]["code"] == "1002"
        assert len(data["items"]) >= 3          # 投资、办公费、提现
        assert data["ending"] == "48500.00"
        # 逐笔方向余额字段存在
        assert "balance_direction" in data["items"][0]

    def test_trial_balance_balanced(self, biz_env):
        """科目余额表：借方余额合计 == 贷方余额合计（会计恒等式）。"""
        from decimal import Decimal
        data = biz_env["c"].get("/api/v1/acc/ledger/trial",
                                params={"period_from": PERIOD, "period_to": PERIOD}).json()
        t = data["totals"]
        assert Decimal(t["debit_balance"]) == Decimal(t["credit_balance"]), \
            f"余额表不平：借 {t['debit_balance']} ≠ 贷 {t['credit_balance']}"
        assert Decimal(t["debit_balance"]) > 0, "余额表不应为空"
        # 本期发生额借贷也应相等
        assert Decimal(t["debit"]) == Decimal(t["credit"]), t
        # 父科目（非末级）余额应等于其下末级科目之和 → 抽查 6602 / 6602.01
        rows = {r["code"]: r for r in data["rows"]}
        assert rows["6602"]["ending"] == rows["6602.01"]["ending"]


# ==================== 列表与筛选（含笛卡尔积回归） ====================

class TestMoveList:

    def test_total_not_multiplied(self, biz_env):
        """回归：total 不能因 select_from 笛卡尔积被放大。"""
        data = _moves(biz_env)
        assert data["total"] == len(data["moves"]), \
            f"total({data['total']}) 与实际返回行数({len(data['moves'])}) 不一致（笛卡尔积？）"

    def test_filter_by_state(self, biz_env):
        r = biz_env["c"].get("/api/v1/acc/moves", params={"state": "posted"})
        assert all(m["state"] == "posted" for m in r.json()["moves"])

    def test_filter_by_period(self, biz_env):
        r = biz_env["c"].get("/api/v1/acc/moves", params={"period": PERIOD})
        assert all(m["period"] == PERIOD for m in r.json()["moves"])

    def test_filter_by_keyword(self, biz_env):
        r = biz_env["c"].get("/api/v1/acc/moves", params={"kw": "销售商品"})
        assert r.json()["total"] >= 1

    def test_filter_by_account(self, biz_env):
        acc_id = _leaf(biz_env, "1122")
        r = biz_env["c"].get("/api/v1/acc/moves", params={"account_id": acc_id})
        assert r.json()["total"] >= 1

    def test_templates_excluded_from_moves(self, biz_env):
        """凭证模板不出现在凭证列表里（也不参与账务）。"""
        r = biz_env["c"].post("/api/v1/acc/templates", json={
            "template_name": "常用：提现",
            "journal_id": _journal(biz_env), "move_date": DATE,
            "lines": [{"summary": "提取现金", "account_id": _leaf(biz_env, "1001")},
                      {"summary": "提取现金", "account_id": _leaf(biz_env, "1002")}]})
        assert r.status_code == 200, r.text
        tpl = r.json()["template"]
        assert tpl["is_template"] is True
        # 模板不带金额
        assert all(l["debit"] == "0.00" and l["credit"] == "0.00" for l in tpl["lines"])

        ids = [m["id"] for m in _moves(biz_env)["moves"]]
        assert tpl["id"] not in ids

        r = biz_env["c"].get("/api/v1/acc/templates")
        assert any(t["id"] == tpl["id"] for t in r.json()["templates"])

        # 模板不能过账
        r = _post(biz_env, tpl["id"])
        assert r.status_code == 400
        assert r.json()["code"] == "template_not_postable"
