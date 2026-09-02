# -*- coding: utf-8 -*-
"""M3 测试：发票 / 自动记账 / 银行对账（项目书 7.6 / 7.7 / 7.8 DoD）。

DoD 对照：
- 7.6：导入 500 行 < 5 秒；重复发票拦截；价税合计 Decimal 精度正确
- 7.7：3 销项 + 2 进项 + 3 流水 → 8 张平衡 draft 凭证且科目金额正确；重复执行不重复生成
- 7.8：编码容错（GBK / UTF-8-BOM）；生成凭证后流水状态联动
"""
import io
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

PERIOD = "2026-09"


@contextmanager
def _new_env():
    """独立账套环境（含科目表 + 6 条种子规则）。"""
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"login": "admin", "password": "admin123"})
        assert r.status_code == 200
        uid = uuid.uuid4().hex[:8]
        r = c.post("/api/v1/biz/books", json={
            "name": f"M3测试公司{uid}", "short_name": f"M3{uid}",
            "credit_no": f"91{uid}M3X", "taxpayer_type": "small",
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


@pytest.fixture(scope="module")
def ae_env():
    """自动记账测试专用账套。

    必须与 TestInvoiceImport 隔离：那里一次性导入了 500 行发票，
    若共用账套，待处理清单会有 500+ 条，无法验证「8 张凭证」的 DoD。
    """
    with _new_env() as e:
        yield e


@pytest.fixture(scope="module")
def bank_env():
    """银行对账测试专用账套（同上，避免被大批量导入污染）。"""
    with _new_env() as e:
        yield e


def _acc(env, code):
    import json
    r = env["c"].get("/api/v1/data/account_account",
                     params={"domain": json.dumps([["code", "=", code]])})
    return r.json()["records"][0]["id"]


def _inv(env, **kw):
    body = {"direction": "output", "invoice_type": "special", "invoice_no": "T001",
            "invoice_date": "2026-09-01", "goods_amount": "1000", "tax_rate": "0.13"}
    body.update(kw)
    return env["c"].post("/api/v1/inv/bills", json=body)


# ==================== 7.6 发票：价税合计精度 ====================

class TestInvoiceAmounts:
    """DoD：价税合计自动计算精度正确（Decimal）。"""

    def test_goods_plus_rate(self, env):
        r = _inv(env, invoice_no="A001", goods_amount="1000", tax_rate="0.13")
        assert r.status_code == 200, r.text
        inv = r.json()["invoice"]
        assert inv["tax_amount"] == "130.00"
        assert inv["total_amount"] == "1130.00"

    def test_rounding_half_up(self, env):
        """333.33 × 13% = 43.3329 → 43.33（四舍五入，不是截断）。"""
        r = _inv(env, invoice_no="A002", goods_amount="333.33", tax_rate="0.13")
        inv = r.json()["invoice"]
        assert inv["tax_amount"] == "43.33"
        assert inv["total_amount"] == "376.66"

    def test_tax_inclusive_reverse(self, env):
        """给价税合计 + 税率 → 反算不含税与税额：1130 / 1.13 = 1000。"""
        r = _inv(env, invoice_no="A003", total_amount="1130", tax_rate="0.13",
                 goods_amount="0")
        inv = r.json()["invoice"]
        assert inv["goods_amount"] == "1000.00"
        assert inv["tax_amount"] == "130.00"

    def test_small_taxpayer_3percent(self, env):
        """小规模 3%：100 / 1.03 = 97.09 + 2.91 = 100（不丢分）。"""
        r = _inv(env, invoice_no="A004", total_amount="100", tax_rate="0.03",
                 goods_amount="0")
        inv = r.json()["invoice"]
        assert Decimal(inv["goods_amount"]) + Decimal(inv["tax_amount"]) == Decimal("100.00")

    def test_zero_rate(self, env):
        r = _inv(env, invoice_no="A005", goods_amount="500", tax_rate="0")
        inv = r.json()["invoice"]
        assert inv["tax_amount"] == "0.00"
        assert inv["total_amount"] == "500.00"


# ==================== 7.6 发票：查重 ====================

class TestInvoiceDedup:
    """DoD：重复发票拦截（同账套 代码+号码+日期）。"""

    def test_duplicate_blocked(self, env):
        r1 = _inv(env, invoice_no="D001", invoice_code="0110", invoice_date="2026-09-05")
        assert r1.status_code == 200, r1.text
        r2 = _inv(env, invoice_no="D001", invoice_code="0110", invoice_date="2026-09-05")
        assert r2.status_code == 400
        assert r2.json()["code"] == "invoice_duplicate"

    def test_same_no_different_date_allowed(self, env):
        """同号码不同日期不算重复（换月重开等场景）。"""
        assert _inv(env, invoice_no="D002", invoice_date="2026-09-05").status_code == 200
        assert _inv(env, invoice_no="D002", invoice_date="2026-09-06").status_code == 200

    def test_import_batch_duplicate_flagged(self, env):
        """导入时批内重复也要标红拦截。"""
        import json
        rows = [{"invoice_no": "B001", "invoice_date": "2026-09-07", "direction": "进项",
                 "goods_amount": "100", "tax_rate": "0.13"},
                {"invoice_no": "B001", "invoice_date": "2026-09-07", "direction": "进项",
                 "goods_amount": "100", "tax_rate": "0.13"}]
        body = {"rows": rows}
        r = env["c"].post("/api/v1/inv/import-commit", json=body)
        assert r.status_code == 400
        assert r.json()["code"] == "rows_invalid"


# ==================== 7.6 发票：导入性能与编码 ====================

def _make_csv(rows, encoding="utf-8-sig"):
    buf = io.StringIO()
    buf.write("方向,发票号码,开票日期,对方名称,不含税金额,税率,费用类别\n")
    for r in rows:
        buf.write(",".join(r) + "\n")
    return buf.getvalue().encode(encoding)


class TestInvoiceImport:
    """DoD：导入 500 行 < 5 秒；编码容错。"""

    def test_import_500_rows_under_5s(self, env):
        rows = [[("进项" if i % 2 else "销项"), f"N{i:05d}", "2026-09-10",
                 f"单位{i}", "1000.00", "0.13", "办公"] for i in range(500)]
        data = _make_csv(rows)

        t0 = time.time()
        r = env["c"].post("/api/v1/inv/import-preview",
                          files={"file": ("inv500.csv", io.BytesIO(data), "text/csv")})
        assert r.status_code == 200, r.text
        prev = r.json()
        assert prev["valid"] == 500, prev

        r2 = env["c"].post("/api/v1/inv/import-commit", json={"rows": prev["preview"]})
        elapsed = time.time() - t0
        assert r2.status_code == 200, r2.text
        assert elapsed < 5, f"500 行导入耗时 {elapsed:.2f}s，超过 5 秒预算"

    def test_gbk_encoding(self, env):
        """GBK 编码的 CSV 不应出现表头乱码。"""
        rows = [["销项", "G001", "2026-09-11", "国标单位", "2000.00", "0.13", ""]]
        data = _make_csv(rows, encoding="gbk")
        r = env["c"].post("/api/v1/inv/import-preview",
                          files={"file": ("gbk.csv", io.BytesIO(data), "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["valid"] == 1
        assert r.json()["preview"][0]["partner_name"] == "国标单位"

    def test_invalid_rows_flagged(self, env):
        """缺号码 / 金额为 0 的行要被标出来，且不入库。"""
        rows = [["销项", "", "2026-09-12", "缺号码", "100", "0.13", ""],
                ["销项", "E002", "2026-09-12", "零金额", "0", "0.13", ""],
                ["销项", "E003", "2026-09-12", "正常", "100", "0.13", ""]]
        data = _make_csv(rows)
        r = env["c"].post("/api/v1/inv/import-preview",
                          files={"file": ("bad.csv", io.BytesIO(data), "text/csv")})
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["valid"] == 1
        assert res["invalid"] == 2
        codes = {e["code"] for e in res["errors"]}
        assert "invoice_no_required" in codes or "amount_invalid" in codes

    def test_month_summary(self, env):
        r = env["c"].get("/api/v1/inv/month-summary", params={"period": PERIOD})
        assert r.status_code == 200
        s = r.json()
        assert "output" in s and "input" in s and "vat_payable" in s
        assert s["output"]["count"] > 0


# ==================== 7.7 自动记账引擎 ====================

class TestAutoEntry:

    def test_seed_rules_created(self, ae_env):
        r = ae_env["c"].get("/api/v1/ae/rules")
        assert r.status_code == 200
        rules = r.json()["rules"]
        assert len(rules) >= 6, f"种子规则应有 6 条，实际 {len(rules)}"
        # 按 priority 升序返回
        assert rules == sorted(rules, key=lambda x: (x["priority"], x["id"]))

    def test_full_chain_8_moves(self, ae_env):
        """DoD：3 销项 + 2 进项 + 3 流水 → 8 张平衡 draft 凭证，科目金额正确。"""
        c = ae_env["c"]
        # —— 3 张销项 ——
        for i, (no, goods, rate) in enumerate([("S1", "100000", "0.13"),
                                               ("S2", "50000", "0.13"),
                                               ("S3", "20000", "0.06")]):
            assert _inv(ae_env, invoice_no=no, direction="output", goods_amount=goods,
                        tax_rate=rate, invoice_date=f"2026-09-0{i + 1}").status_code == 200
        # —— 2 张进项 ——
        for i, (no, goods, rate, cat) in enumerate([("P1", "30000", "0.13", "material"),
                                                    ("P2", "1060", "0.06", "telecom")]):
            assert _inv(ae_env, invoice_no=no, direction="input", goods_amount=goods,
                        tax_rate=rate, category=cat,
                        invoice_date=f"2026-09-0{i + 4}").status_code == 200
        # —— 3 条流水 ——
        rows = [
            {"trade_date": "2026-09-10", "summary": "代发工资", "counterpart_name": "工资户",
             "debit": "0", "credit": "45000.00", "balance": "455000.00"},
            {"trade_date": "2026-09-15", "summary": "缴纳增值税", "counterpart_name": "税务局",
             "debit": "0", "credit": "13000.00", "balance": "442000.00"},
            {"trade_date": "2026-09-20", "summary": "收到货款", "counterpart_name": "客户A",
             "debit": "113000.00", "credit": "0", "balance": "555000.00"},
        ]
        r = c.post("/api/v1/bank/import-commit", json={"rows": rows, "bank_alias": "工行"})
        assert r.status_code == 200, r.text

        # —— 待处理清单 ——
        pend = c.get("/api/v1/ae/pending", params={"period": PERIOD}).json()
        assert pend["total"] == 8, pend
        assert pend["matched"] == 8, f"应有 8 条全部命中规则，实际 {pend['matched']}"

        # —— 批量执行 ——
        items = [{"source_model": i["source_model"], "source_id": i["source_id"],
                  "rule_id": i["rule_id"]} for i in pend["items"] if i["matched"]]
        res = c.post("/api/v1/ae/execute", json={"items": items}).json()
        assert res["ok"] == 8, res
        assert res["failed"] == 0, res

        # —— 校验每张凭证：平衡 + 状态为 draft ——
        for d in res["details"]["ok"]:
            mv = c.get(f"/api/v1/acc/moves/{d['move_id']}").json()["move"]
            assert mv["diff"] == "0.00", f"凭证 #{mv['id']} 不平衡：{mv}"
            assert mv["state"] == "draft", "自动记账生成的是草稿，需人工确认后过账"

    def test_generated_accounts_and_amounts_correct(self, ae_env):
        """校验关键凭证的科目与金额（销项：借1122 / 贷6001 + 贷2221.01.01）。"""
        c = ae_env["c"]
        mv = c.get("/api/v1/acc/moves", params={"limit": 100}).json()["moves"]
        auto = [m for m in mv if m["source_type"] in ("auto_invoice", "auto_bank")]
        assert len(auto) == 8

        # 找销项 S1（113000）这张
        target = None
        for m in auto:
            d = c.get(f"/api/v1/acc/moves/{m['id']}").json()["move"]
            if abs(float(d["total_debit"]) - 113000) < 0.01 and \
                    any(l["account_code"] == "6001" for l in d["lines"]):
                target = d
                break
        assert target is not None, "未找到 S1 销项凭证"
        by_acc = {l["account_code"]: l for l in target["lines"]}
        assert set(by_acc) == {"1122", "6001", "2221.01.01"}
        assert by_acc["1122"]["debit"] == "113000.00"
        assert by_acc["6001"]["credit"] == "100000.00"
        assert by_acc["2221.01.01"]["credit"] == "13000.00"

    def test_idempotent_repeat_execution(self, ae_env):
        """DoD：同批重复执行不重复生成。"""
        c = ae_env["c"]
        pend = c.get("/api/v1/ae/pending", params={"period": PERIOD}).json()
        # 全部已生成 → 待处理清单应为空
        assert pend["total"] == 0, f"凭证已生成，待处理清单应为空，实际 {pend['total']}"

        # 强行再执行一次（模拟用户重复点击）。
        # 注意：invoice_bill 的 id 是跨账套全局自增的，不能硬编码 1，
        # 必须取本账套里已生成过凭证的真实 id。
        done = c.get("/api/v1/inv/bills",
                     params={"state": "entry_generated", "limit": 1}).json()["invoices"]
        assert done, "应存在已生成凭证的发票"
        res = c.post("/api/v1/ae/execute", json={
            "items": [{"source_model": "invoice_bill", "source_id": done[0]["id"]}]}).json()
        assert res["ok"] == 0, res
        assert res["skipped"] == 1, res

    def test_unbalanced_template_rejected(self, ae_env):
        """引擎铁律：模板借贷不平衡 → 整单拒绝并写日志。"""
        c = ae_env["c"]
        r = c.post("/api/v1/ae/rules", json={
            "name": "不平衡测试规则", "trigger": "bank_line",
            "match_condition": {"summary_ilike": "不平衡测试"},
            "line_template": [{"side": "debit", "account": "1002", "amount": "{debit}"},
                              {"side": "credit", "account": "1122", "amount": "={debit}*2"}],
            "priority": 1,
        })
        assert r.status_code == 200, r.text
        rule_id = r.json()["rule"]["id"]

        # 造一条流水
        c.post("/api/v1/bank/import-commit", json={"rows": [
            {"trade_date": "2026-09-25", "summary": "不平衡测试流水",
             "debit": "1000.00", "credit": "0", "balance": "1000.00"}]})

        pend = c.get("/api/v1/ae/pending", params={"period": PERIOD}).json()
        item = next((i for i in pend["items"]
                     if i["source"].get("summary") == "不平衡测试流水"), None)
        assert item is not None
        assert item["matched"] is False, "不平衡模板应被判为不可执行"
        assert "不平衡" in (item.get("error") or ""), item

        # 强行执行也应失败并记日志
        res = c.post("/api/v1/ae/execute", json={
            "items": [{"source_model": "bank_statement_line",
                       "source_id": item["source_id"], "rule_id": rule_id}]}).json()
        assert res["failed"] == 1
        assert res["ok"] == 0

        logs = c.get("/api/v1/ae/logs", params={"result": "failed"}).json()["logs"]
        assert any("不平衡" in (l["message"] or "") for l in logs)

        # 清理：停用该规则，避免影响其他测试
        c.delete(f"/api/v1/ae/rules/{rule_id}")


# ==================== 7.8 银行对账 ====================

class TestBankReconcile:

    def test_gbk_bank_file(self, bank_env):
        """DoD：GBK 编码的银行对账单能被正确识别（防表头乱码）。"""
        lines = ["交易日期,流水号,对方户名,摘要,收入金额,支出金额,余额",
                 "2026-09-01,BK01,某供应商,采购付款,0,5000.00,95000.00",
                 "2026-09-02,BK02,某客户,收到货款,20000.00,0,115000.00"]
        data = ("\r\n".join(lines) + "\r\n").encode("gbk")
        r = bank_env["c"].post("/api/v1/bank/import-preview",
                          files={"file": ("bank_gbk.csv", io.BytesIO(data), "text/csv")})
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["valid"] == 2, res
        assert res["preview"][0]["summary"] == "采购付款"

    def test_utf8_bom_bank_file(self, bank_env):
        data = ("交易日期,对方户名,摘要,收入金额,支出金额,余额\n"
                "2026-09-03,客户B,收到货款,8000.00,0,123000.00\n").encode("utf-8-sig")
        r = bank_env["c"].post("/api/v1/bank/import-preview",
                          files={"file": ("bank_u8.csv", io.BytesIO(data), "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["valid"] == 1

    def test_generate_move_links_state(self, bank_env):
        """DoD：生成凭证后流水状态联动为已对账。"""
        c = bank_env["c"]
        c.post("/api/v1/bank/import-commit", json={"rows": [
            {"trade_date": "2026-09-28", "summary": "收到货款", "counterpart_name": "客户C",
             "debit": "30000.00", "credit": "0", "balance": "153000.00"}]})

        lines = c.get("/api/v1/bank/lines", params={"period": PERIOD,
                                                    "state": "unreconciled"}).json()["lines"]
        target = next(l for l in lines if l["counterpart_name"] == "客户C")
        assert target["state"] == "unreconciled"

        r = c.post(f"/api/v1/bank/lines/{target['id']}/generate-move", json={})
        assert r.status_code == 200, r.text
        move_id = r.json()["move_id"]

        after = c.get("/api/v1/bank/lines", params={"period": PERIOD}).json()["lines"]
        updated = next(l for l in after if l["id"] == target["id"])
        assert updated["state"] == "reconciled"
        assert updated["move_id"] == move_id

    def test_month_summary_balance(self, bank_env):
        """期初 + 收入 - 支出 = 期末。"""
        s = bank_env["c"].get("/api/v1/bank/month-summary", params={"period": PERIOD}).json()
        opening, debit, credit, closing = (Decimal(s["opening"]), Decimal(s["debit"]),
                                           Decimal(s["credit"]), Decimal(s["closing"]))
        assert opening + debit - credit == closing
