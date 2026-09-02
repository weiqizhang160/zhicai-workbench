# -*- coding: utf-8 -*-
"""给 1 号账套灌入 M2 演示账务数据（投资/销售/费用/提现 + 期末结转）。

用途：截图验收、手工验收。可重复执行（会先清空该账套的凭证）。
运行：先启动服务，然后 `python tools/demo_data.py`
"""
import http.cookiejar
import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
PERIOD = "2026-09"
BOOK_ID = 1
DB_PATH = "data/zhicai.db"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with opener.open(req, timeout=20) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt else {}


def leaf(code):
    r = call("GET", "/api/v1/acc/accounts/leaf?kw=" + urllib.parse.quote(code))
    for a in r["accounts"]:
        if a["code"] == code:
            return a["id"]
    raise SystemExit(f"末级科目不存在：{code}")


def main():
    # 直接清空该账套的演示凭证（避免与上次的结转/红冲残留冲突）。
    # 仅做演示用，业务层不该这么做。
    import sqlite3
    con = sqlite3.connect(DB_PATH)
    moved_ids = [r[0] for r in con.execute(
        "SELECT id FROM account_move WHERE book_id=?", (BOOK_ID,)).fetchall()]
    if moved_ids:
        n_lines = con.execute(
            f"DELETE FROM account_move_line WHERE move_id IN ({','.join('?'*len(moved_ids))})",
            moved_ids).rowcount
        n_moves = con.execute(
            f"DELETE FROM account_move WHERE id IN ({','.join('?'*len(moved_ids))})",
            moved_ids).rowcount
        # 清掉结账锁定记录
        con.execute("DELETE FROM account_period_close WHERE book_id=?", (BOOK_ID,))
        con.commit()
        print(f"  清空 {n_moves} 张凭证 / {n_lines} 行分录（含历史结转/红冲）")
    con.close()

    call("POST", "/api/v1/auth/login", {"login": "admin", "password": "admin123"})
    call("PUT", f"/api/v1/biz/books/{BOOK_ID}/switch")

    # 往来单位
    r = call("POST", "/api/v1/data/res_partner",
             {"values": {"name": "深圳市宏远贸易有限公司", "partner_type": "customer"}})
    pid = r["record"]["id"]

    journals = call("GET", "/api/v1/acc/journals")["journals"]
    jid = next(j["id"] for j in journals if j["code"] == "记")

    moves = [
        ("2026-09-01", "收到股东投资款", [
            {"summary": "收到股东投资款", "account_id": leaf("1002"), "debit": "500000", "credit": "0"},
            {"summary": "收到股东投资款", "account_id": leaf("3001"), "debit": "0", "credit": "500000"},
        ]),
        ("2026-09-05", "销售五金制品一批", [
            {"summary": "销售五金制品", "account_id": leaf("1122"), "debit": "113000", "credit": "0",
             "partner_id": pid},
            {"summary": "主营业务收入", "account_id": leaf("6001"), "debit": "0", "credit": "100000",
             "partner_id": pid},
            {"summary": "销项税额", "account_id": leaf("2221.01.01"), "debit": "0", "credit": "13000"},
        ]),
        ("2026-09-08", "采购库存商品", [
            {"summary": "采购库存商品", "account_id": leaf("1405"), "debit": "60000", "credit": "0"},
            {"summary": "进项税额", "account_id": leaf("2221.01.02"), "debit": "7800", "credit": "0"},
            {"summary": "支付货款", "account_id": leaf("1002"), "debit": "0", "credit": "67800"},
        ]),
        ("2026-09-12", "支付办公费用", [
            {"summary": "购买办公用品", "account_id": leaf("6602.01"), "debit": "1200", "credit": "0"},
            {"summary": "支付网费", "account_id": leaf("6602.06"), "debit": "300", "credit": "0"},
            {"summary": "支付办公费", "account_id": leaf("1002"), "debit": "0", "credit": "1500"},
        ]),
        ("2026-09-15", "提取备用金", [
            {"summary": "提取备用金", "account_id": leaf("1001"), "debit": "20000", "credit": "0"},
            {"summary": "提取备用金", "account_id": leaf("1002"), "debit": "0", "credit": "20000"},
        ]),
        ("2026-09-20", "支付工资", [
            {"summary": "计提管理人员工资", "account_id": leaf("6602.07"), "debit": "30000", "credit": "0"},
            {"summary": "代扣个税", "account_id": leaf("2211.01"), "debit": "0", "credit": "1200"},
            {"summary": "发放工资", "account_id": leaf("1002"), "debit": "0", "credit": "28800"},
        ]),
        ("2026-09-25", "收到客户回款", [
            {"summary": "收到宏远贸易回款", "account_id": leaf("1002"), "debit": "80000", "credit": "0"},
            {"summary": "冲减应收账款", "account_id": leaf("1122"), "debit": "0", "credit": "80000",
             "partner_id": pid},
        ]),
    ]

    posted = []
    for date, desc, lines in moves:
        r = call("POST", "/api/v1/acc/moves",
                 {"journal_id": jid, "move_date": date, "attachment_count": 1,
                  "remark": desc, "lines": lines})
        mid = r["move"]["id"]
        p = call("POST", f"/api/v1/acc/moves/{mid}/post")
        posted.append((mid, p["move"]["name"]))
        print(f"  过账 {p['move']['name']}  {desc}")

    # 期末结转
    try:
        r = call("POST", "/api/v1/acc/carry-forward", {"period": PERIOD})
        print(f"  结转凭证 {r['move']['name']}  损益 → 本年利润 {r['move']['total_credit']}")
    except Exception as e:
        print("  结转：", e)

    # 校验输出
    bs = call("GET", f"/api/v1/acc/report/balance-sheet?period={PERIOD}")
    pl = call("GET", f"/api/v1/acc/report/income?period_from={PERIOD}&period_to={PERIOD}")
    print()
    print(f"  资产负债表：资产 {bs['total_assets']} / 负债+权益 {bs['total_liab_equity']} "
          f"{'平衡 ✓' if bs['balanced'] else '不平衡 ✗ 差额 ' + bs['diff']}")
    print(f"  利润表：净利润 {pl['net_profit']} / 本年利润发生额 {pl['profit_account_move']} "
          f"{'一致 ✓' if pl['consistent'] else '不一致 ✗'}")


if __name__ == "__main__":
    main()
