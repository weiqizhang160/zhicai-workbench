# -*- coding: utf-8 -*-
"""M6 演示：外贸专区 + 工资社保 + 文档中心（项目书 7.10 / 7.11 / 7.12）。

流程：登录 → 建外贸账套 → 登记报关单（含商品行）→ 收汇（分两笔）→
      出口退税流转 → 平台链接 → 工资批次（录员工行 + 个税自动算 + 确认生成凭证）→
      文档中心（上传营业执照 PDF + 反查发票影像）。

运行：先启动服务，然后 `python tools/demo_data_m6.py`
"""
import http.cookiejar
import json
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


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


def multipart(path, fields, files):
    """简易 multipart 上传。files: [(字段名, 文件名, 字节)]"""
    boundary = "----zcBoundary7dMA3x"
    parts = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                     f'name="{k}"\r\n\r\n{v}\r\n'.encode())
    for field, fname, raw in files:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                     f'name="{field}"; filename="{fname}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode()
                     + raw + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with opener.open(req, timeout=60) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt else {}


PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
       b"trailer<</Root 1 0 R>>\n%%EOF")


def main():
    call("POST", "/api/v1/auth/login", {"login": "admin", "password": "admin123"})

    # ---- 0. 建外贸账套 ----
    print("[0] 新建外贸客户账套")
    import uuid
    uid = uuid.uuid4().hex[:6]
    books = call("GET", "/api/v1/biz/books")["books"]
    # 复用已有的外贸演示账套，没有则新建
    bid = next((b["id"] for b in books if b.get("is_foreign_trade")), None)
    if bid:
        print(f"    复用已有外贸账套 id={bid}")
    else:
        r = call("POST", "/api/v1/biz/books", {
            "name": f"深圳跨境贸易{uid}有限公司", "short_name": f"跨境{uid}",
            "credit_no": f"91{uid}FTX", "taxpayer_type": "general",
            "accounting_standard": "general", "is_foreign_trade": True,
        })
        bid = r["book"]["id"]
        print(f"    已创建：{r['book']['name']}（id={bid}）")
    call("PUT", f"/api/v1/biz/books/{bid}/switch")

    # ---- 1. 报关单 ----
    print("\n[1] 登记报关单（FOB USD 20000，1 个商品行）")
    decl = call("POST", "/api/v1/ft/decls", {
        "decl_no": f"D202608{uid.upper()}001", "export_date": "2026-08-05",
        "trade_mode": "FOB", "currency": "USD", "fx_rate": "7.15",
        "usd_amount": "20000", "customer_abroad": "Pacific Hardware Ltd.",
        "goods_count": 120,
        "lines": [{"hs_code": "8205590000", "goods_name": "手工工具套装",
                   "qty": "1200", "unit": "件", "unit_price": "16.67", "amount": "20000"}],
    })["decl"]
    print(f"    报关单 {decl['decl_no']}：USD {decl['usd_amount']} / "
          f"¥{decl['cny_total']}，未收差额 {decl['unreceived']}")

    # ---- 2. 收汇（两笔）----
    print("\n[2] 登记收汇（分两笔：12000 + 8000）")
    for date_, amt, kind in (("2026-08-20", "12000", "receipt"),
                             ("2026-09-05", "8000", "settlement")):
        call("POST", "/api/v1/ft/fx-receipts", {
            "decl_id": decl["id"], "receipt_date": date_, "amount": amt,
            "fx_rate": "7.15", "kind": kind, "bank_fee": "50",
        })
    detail = call("GET", f"/api/v1/ft/decls/{decl['id']}")["decl"]
    print(f"    已收汇 {detail['received_amount']}，未收差额 {detail['unreceived']}")

    # ---- 3. 出口退税流转 ----
    print("\n[3] 出口退税（2600 元，流转到已到账）")
    refund = call("POST", "/api/v1/ft/refunds", {
        "decl_id": decl["id"], "period": "2026-09", "kind": "免抵退",
        "refund_amount": "2600"})["refund"]
    for status in ("submitted", "approved", "received"):
        call("POST", f"/api/v1/ft/refunds/{refund['id']}/status",
             {"status": status,
              "received_date": "2026-09-20" if status == "received" else None})
    print(f"    退税 #{refund['id']} 已流转到 received（到账 2026-09-20）")

    # ---- 4. 平台链接 ----
    print("\n[4] 平台链接中心")
    plat = call("GET", "/api/v1/ft/platform")
    for key, p in plat["links"].items():
        print(f"    {p['name']:<22s} {p['url']}")
    call("PUT", "/api/v1/ft/platform/notes",
          {"notes": "单一窗口用法人卡登录；报关单在「综合查询 → 报关单查询」导出 CSV。"})
    print("    操作备注已保存")

    # ---- 5. 工资批次 ----
    print("\n[5] 工资批次（2026-08，2 名员工，个税自动算）")
    period = "2026-08"
    exist = call("GET", "/api/v1/payroll/batches", params={"book_id": bid})["items"]
    batch = next((b for b in exist if b["period"] == period), None)
    if batch:
        print(f"    {period} 批次已存在（id={batch['id']}），跳过创建")
    else:
        batch = call("POST", "/api/v1/payroll/batches", {"period": period})["batch"]
    if batch["state"] == "draft":
        for name, gross, se, sr, fe in (("王大力", "12000", "1800", "3200", "1200"),
                                        ("刘小美", "7000", "900", "1600", "600")):
            call("POST", f"/api/v1/payroll/batches/{batch['id']}/lines", {
                "employee_name": name, "gross_salary": gross,
                "social_employee": se, "social_employer": sr, "fund_employer": fe})
        batch = call("GET", f"/api/v1/payroll/batches/{batch['id']}")["batch"]
    for ln in batch.get("lines", []):
        print(f"    {ln['employee_name']:<8s} 应发 {ln['gross_salary']:>9s} "
              f"个税 {ln['iit']:>7s} 实发 {ln['net_salary']:>9s}")
    print(f"    合计：{batch['employee_count']} 人，应发 {batch['total_gross']}，"
          f"实发 {batch['total_net']}")
    if batch["state"] == "draft":
        r = call("POST", f"/api/v1/payroll/batches/{batch['id']}/confirm")
        batch = r["batch"]
        print(f"    已确认：计提凭证 #{batch['accrual_move_id']} + "
              f"发放凭证 #{batch['payment_move_id']}（草稿）")

    # ---- 6. 文档中心 ----
    print("\n[6] 文档中心")
    r = multipart("/api/v1/docs/upload",
                  {"book_id": str(bid), "doc_type": "license", "tags": "证照,工商",
                   "doc_year": "2026", "name": f"营业执照-{uid}"},
                  [("files", f"license-{uid}.pdf", PDF)])
    print(f"    上传营业执照 PDF：{r['count']} 个文件")
    r = multipart("/api/v1/docs/upload",
                  {"book_id": str(bid), "doc_type": "customs", "tags": "报关单",
                   "doc_year": "2026"},
                  [("files", f"decl-{uid}-01.pdf", PDF),
                   ("files", f"decl-{uid}-02.pdf", PDF)])
    print(f"    上传报关单扫描件：{r['count']} 个文件")

    docs = call("GET", "/api/v1/docs", params={"limit": 500})["records"]
    print(f"    文档中心共 {len(docs)} 份文档（跨账套）：")
    for d in docs[:8]:
        print(f"      · [{d['doc_type']:<11s}] {d['book_name']} / {d['name']}"
              f"（{d['file_size']} 字节{'，可预览' if d['previewable'] else ''}）")

    # ---- 7. 外贸汇总 ----
    print("\n[7] 外贸汇总")
    s = call("GET", "/api/v1/ft/summary")
    print(f"    报关单 {s['decl_count']} 张，总额 ¥{s['total_cny']}，"
          f"已收 ¥{s['received_cny']}，未收 ¥{s['unreceived_cny']}，"
          f"退税在途 {s['refund_pending_count']} 笔")
    print("\n演示完成。打开 http://127.0.0.1:8000 查看外贸专区 / 工资社保 / 文档中心。")


if __name__ == "__main__":
    main()
