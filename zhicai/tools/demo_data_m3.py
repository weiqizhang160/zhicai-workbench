# -*- coding: utf-8 -*-
"""M3 演示数据：3 张销项票 + 2 张进项票 + 3 条银行流水 → 批量自动记账生成 8 张凭证。

对齐项目书 7.7 DoD：批量执行后生成 8 张**平衡**的 draft 凭证，科目与金额全部正确；
同批重复执行不重复生成。

运行：先启动服务，然后 `python tools/demo_data_m3.py [book_id]`
"""
import http.cookiejar
import json
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
BOOK_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with opener.open(req, timeout=30) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt else {}


# 3 张销项 + 2 张进项
INVOICES = [
    # direction, no,   date,        partner,        goods,   rate, category
    ("output", "S001", "2026-09-03", "宏远贸易", "100000", "0.13", None),
    ("output", "S002", "2026-09-11", "南海五金", "50000", "0.13", None),
    ("output", "S003", "2026-09-19", "宏远贸易", "20000", "0.06", None),
    ("input", "P001", "2026-09-05", "华强材料", "30000", "0.13", "material"),
    ("input", "P002", "2026-09-14", "电信深圳", "1060", "0.06", "telecom"),
]

# 3 条流水：工资支出 / 缴税支出 / 客户回款（收入）
BANK_ROWS = [
    {"trade_date": "2026-09-10", "trade_no": "W001", "counterpart_name": "代发工资户",
     "summary": "代发工资", "debit": "0", "credit": "45000.00", "balance": "455000.00"},
    {"trade_date": "2026-09-15", "trade_no": "T001", "counterpart_name": "税务局",
     "summary": "缴纳增值税", "debit": "0", "credit": "13000.00", "balance": "442000.00"},
    {"trade_date": "2026-09-20", "trade_no": "R001", "counterpart_name": "宏远贸易",
     "summary": "收到货款", "debit": "113000.00", "credit": "0", "balance": "555000.00"},
]


def main():
    call("POST", "/api/v1/auth/login", {"login": "admin", "password": "admin123"})
    call("PUT", f"/api/v1/biz/books/{BOOK_ID}/switch")
    print(f"账套 {BOOK_ID}")

    # ---- 1. 建发票 ----
    print("\n[1] 录入发票")
    for direction, no, dt, partner, goods, rate, cat in INVOICES:
        r = call("POST", "/api/v1/inv/bills", {
            "direction": direction, "invoice_type": "special",
            "invoice_code": "011002100411", "invoice_no": no, "invoice_date": dt,
            "partner_name": partner, "goods_amount": goods, "tax_rate": rate,
            "category": cat, "remark": "M3 演示",
        })
        inv = r["invoice"]
        print(f"   {direction:6s} {no}  不含税 {inv['goods_amount']:>10s} "
              f"税 {inv['tax_amount']:>9s}  价税合计 {inv['total_amount']:>10s}")

    # ---- 2. 导入流水 ----
    print("\n[2] 导入银行流水")
    r = call("POST", "/api/v1/bank/import-commit",
             {"rows": BANK_ROWS, "bank_alias": "工行", "account_no": "4000****1234"})
    print(f"   批次 #{r['statement_id']}，{r['imported']} 行")

    # ---- 3. 待处理清单 ----
    print("\n[3] 待处理清单（规则匹配预览）")
    pend = call("GET", "/api/v1/ae/pending?period=2026-09")
    print(f"   共 {pend['total']} 条，命中规则 {pend['matched']} 条，"
          f"未匹配 {pend['unmatched']} 条")
    for it in pend["items"]:
        flag = "✓" if it["matched"] else "✗"
        src = it["source_model"]
        name = (it["source"].get("invoice_no") or it["source"].get("summary") or
                it["source"].get("counterpart_name"))
        rule = it["rule_name"] or (it.get("error") or "")
        print(f"   {flag} {src:22s} {str(name):12s} 借{it['total_debit']:>10s} "
              f"贷{it['total_credit']:>10s}  {rule}")

    # ---- 4. 批量执行 ----
    print("\n[4] 批量执行")
    items = [{"source_model": i["source_model"], "source_id": i["source_id"],
              "rule_id": i["rule_id"]}
             for i in pend["items"] if i["matched"]]
    res = call("POST", "/api/v1/ae/execute", {"items": items})
    print(f"   成功 {res['ok']} / 失败 {res['failed']} / 跳过 {res['skipped']}")
    for d in res["details"]["ok"]:
        print(f"   ✓ {d['source_model']}#{d['source_id']} → 凭证 #{d['move_id']} "
              f"（{d['rule_name']}）")
    for d in res["details"]["failed"]:
        print(f"   ✗ {d['source_model']}#{d['source_id']} → {d['message']}")

    # ---- 5. 重复执行（幂等） ----
    print("\n[5] 重复执行同一批（验证幂等）")
    res2 = call("POST", "/api/v1/ae/execute", {"items": items})
    print(f"   成功 {res2['ok']} / 失败 {res2['failed']} / 跳过 {res2['skipped']}")
    for d in res2["details"]["skipped"]:
        print(f"   - 已跳过：{d['message']}")

    # ---- 6. 校验生成的凭证 ----
    print("\n[6] 校验生成的凭证（应全部借贷平衡）")
    mv = call("GET", "/api/v1/acc/moves?limit=100")
    auto = [m for m in mv["moves"] if m["source_type"] in ("auto_invoice", "auto_bank")]
    print(f"   自动生成的凭证：{len(auto)} 张")
    balanced = 0
    for m in sorted(auto, key=lambda x: x["id"]):
        d = call("GET", f"/api/v1/acc/moves/{m['id']}")
        mm = d["move"]
        ok = mm["diff"] == "0.00"
        balanced += 1 if ok else 0
        print(f"   {'✓' if ok else '✗'} #{mm['id']} {mm['move_date']} "
              f"借{mm['total_debit']:>10s} 贷{mm['total_credit']:>10s}  "
              f"{[l['summary'] for l in mm['lines']][:2]}")
    print(f"\n   平衡凭证：{balanced}/{len(auto)}")

    # ---- 7. 月末视图 ----
    print("\n[7] 发票月末视图（申报底稿取数）")
    ms = call("GET", "/api/v1/inv/month-summary?period=2026-09")
    print(f"   销项：{ms['output']['count']} 张，不含税 {ms['output']['goods']}，"
          f"税额 {ms['output']['tax']}")
    print(f"   进项：{ms['input']['count']} 张，不含税 {ms['input']['goods']}，"
          f"税额 {ms['input']['tax']}")
    print(f"   应纳税额（销项-进项）：{ms['vat_payable']}")

    print("\n[8] 银行月度对账汇总")
    bs = call("GET", "/api/v1/bank/month-summary?period=2026-09")
    print(f"   期初 {bs['opening']} + 收入 {bs['debit']} - 支出 {bs['credit']} "
          f"= 期末 {bs['closing']}")
    print(f"   已对账 {bs['reconciled']} 条 / 未对账 {bs['unreconciled']} 条")


if __name__ == "__main__":
    main()
