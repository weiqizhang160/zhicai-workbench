# -*- coding: utf-8 -*-
"""M5 演示：合同收费 + 任务看板 + 仪表盘（项目书 7.2 / 7.4）。

流程：登录 → 选账套 → 建代账合同（自动生成收费计划）→ 批量收款 →
      应收报表 → 逾期/续约扫描 → 任务看板 → 首页仪表盘。

运行：先启动服务，然后 `python tools/demo_data_m5.py [book_id]`
（book_id 缺省取第一个客户账套）
"""
import http.cookiejar
import json
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
BOOK_ID = int(sys.argv[1]) if len(sys.argv) > 1 else None

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

FEE_STATE = {"unpaid": "未收款", "invoiced": "已开票", "paid": "已收款", "overdue": "已逾期"}


def call(method, path, body=None, params=None):
    data = json.dumps(body).encode() if body is not None else None
    url = BASE + path
    if params:
        url += ("?" + urllib.parse.urlencode(params))
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with opener.open(req, timeout=60) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt else {}


def main():
    call("POST", "/api/v1/auth/login", {"login": "admin", "password": "admin123"})

    # ---- 0. 选账套 ----
    books = call("GET", "/api/v1/biz/books")["books"]
    if not books:
        print("没有可用账套，请先运行 demo_data.py 建客户")
        return
    bid = BOOK_ID or books[0]["id"]
    call("PUT", f"/api/v1/biz/books/{bid}/switch")
    book_name = next((b["short_name"] for b in books if b["id"] == bid), f"#{bid}")
    print(f"账套：{book_name}（id={bid}）")

    # ---- 1. 建合同（自动生成收费计划）----
    print("\n[1] 新建代账合同（按月，2026-01-01 ~ 2026-12-31，300 元/期）")
    r = call("POST", "/api/v1/contract/agreements", {
        "book_id": bid,
        "start_date": "2026-01-01", "end_date": "2026-12-31",
        "service_scope": ["bookkeeping", "tax_return"],
        "fee_type": "monthly", "fee_amount": "300",
        "payer_name": "M5 演示客户",
    })
    ag = r["agreement"]
    print(f"    合同 {ag['contract_no']} 已创建，收费计划新建 {r['fee']['created']} 期"
          f"（跳过 {r['fee']['skipped']} 期）")

    # ---- 2. 批量收款（前 3 期）----
    print("\n[2] 批量收款：收前 3 期")
    items = call("GET", "/api/v1/contract/fee-items",
                 params={"book_id": bid, "limit": 2000})["items"]
    ag_items = [i for i in items if i["agreement_id"] == ag["id"]]
    to_collect = ag_items[:3]
    rr = call("POST", "/api/v1/contract/fee-items/bulk-collect", {
        "fee_item_ids": [i["id"] for i in to_collect],
        "paid_date": "2026-03-01",
    })
    print(f"    已收款 {rr['collected']} 期：{', '.join(i['period'] for i in to_collect)}")

    # ---- 3. 逾期/续约扫描 ----
    print("\n[3] 逾期/续约扫描（幂等）")
    scan = call("POST", "/api/v1/contract/scan")
    print(f"    逾期标红 {scan['overdue_marked']} 期，新增催收任务 {scan['collection_tasks']} 条，"
          f"续约提醒 {scan['renewal_tasks']} 条")
    scan2 = call("POST", "/api/v1/contract/scan")
    print(f"    再次扫描：新增催收任务 {scan2['collection_tasks']} 条（幂等，应为 0）")

    # ---- 4. 应收报表 ----
    print("\n[4] 应收报表")
    rep = call("GET", "/api/v1/contract/report/receivable")
    print(f"    本年度已收合计：¥{rep['year_received']}")
    for row in rep["by_book"]:
        print(f"    {row['book_name']:<16s} 应收 ¥{row['receivable']:>10s} "
              f"已收 ¥{row['received']:>10s} 逾期 ¥{row['overdue']:>10s}")

    # ---- 5. 任务看板 ----
    print("\n[5] 任务看板（按状态四列）")
    kanban = call("GET", "/api/v1/tasks/kanban")["columns"]
    for col in kanban:
        names = [t["title"] for t in col["items"]]
        print(f"    {col['state']:<12s} {len(col['items'])} 条"
              + (f" → {names[:3]}" if names else ""))

    # ---- 6. 首页仪表盘 ----
    print("\n[6] 首页仪表盘（总览，跨账套聚合）")
    d = call("GET", "/api/v1/dashboard/summary")
    o = d["overview"]
    print(f"    本月概览：服务客户 {o['normal_books']}/{o['total_books']}，"
          f"待过账凭证 {o['draft_moves']}，已过账 {o['posted_moves']}，新发票 {o['new_invoices']}")
    print(f"    逾期预警：逾期未申报 {d['overdue']['decl']}，逾期未收代账费 {d['overdue']['fee']}")
    fm = d["fee_month"]
    print(f"    本月收款：应收 ¥{fm['receivable']} / 已收 ¥{fm['received']} / 未收 ¥{fm['unpaid']}")
    print(f"    待办任务：{len(d['todo_tasks'])} 条")
    for t in d["todo_tasks"][:5]:
        print(f"      · {t['title']}（{t['priority']}）")
    print(f"    各客户进度：{len(d['progress'])} 家")
    for p in d["progress"][:5]:
        print(f"      · {p['code']} {p['short_name']}: 收票 {p['invoice']['count']} / "
              f"凭证 {p['move']['posted']} / 申报 {p['decl']['done']}/{p['decl']['total']} / "
              f"收费 {p['fee']['done']}/{p['fee']['total']}")


if __name__ == "__main__":
    main()
