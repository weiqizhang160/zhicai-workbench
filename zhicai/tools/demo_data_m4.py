# -*- coding: utf-8 -*-
"""M4 演示：批量生成申报台账 → 逐笔计算底稿 → 打印申报日历汇总。

运行：先启动服务，然后 `python tools/demo_data_m4.py [period]`
（period 默认 2026-09；若是季末月会自动带上季度属期，如 2026Q3）
"""
import http.cookiejar
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
PERIOD = sys.argv[1] if len(sys.argv) > 1 else "2026-09"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

KIND_LABEL = {
    "vat": "增值税", "surtax": "附加税", "cit_quarterly": "所得税(季)",
    "cit_annual": "所得税(年报)", "iit": "个人所得税", "stamp": "印花税",
}
STATE_LABEL = {
    "pending": "待申报", "preparing": "准备中", "submitted": "已申报",
    "paid": "已缴款", "done": "已完成", "exempt": "免税/零申报",
}


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with opener.open(req, timeout=60) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt else {}


def main():
    call("POST", "/api/v1/auth/login", {"login": "admin", "password": "admin123"})

    # ---- 1. 批量生成（幂等）----
    print(f"[1] 批量生成 {PERIOD} 申报台账")
    res = call("POST", "/api/v1/tax/generate", {"periods": [PERIOD]})
    print(f"    新建 {res['created']} 条 / 跳过 {res['skipped']} 条 "
          f"/ 覆盖 {res['books']} 个账套")
    print(f"    属期展开：{res['periods']}")

    # ---- 2. 取全部台账 ----
    items = call("GET", "/api/v1/tax/items?limit=500")["items"]
    print(f"\n[2] 台账共 {len(items)} 条")

    # ---- 3. 逐笔计算 ----
    print("\n[3] 逐笔计算底稿")
    done = []
    for it in items:
        try:
            r = call("POST", f"/api/v1/tax/items/{it['id']}/compute", {})
            done.append((it, r["snapshot"]))
        except Exception as e:
            print(f"    ✗ {it['book_name']} {it['tax_kind']}：{e}")

    # 按账套 + 税种展示
    for it, snap in done:
        if not snap:
            continue
        print(f"    ── {it['book_name']} · {KIND_LABEL.get(it['tax_kind'], it['tax_kind'])}"
              f" · 属期 {it['period']}")
        print(f"       公式：{snap['formula']}")
        for d in snap["items"][-4:]:          # 只打印关键几行
            src = ""
            if d.get("source"):
                s = d["source"]
                if s.get("type") == "invoice":
                    src = f"  ← 发票·{'销项' if s.get('direction') == 'output' else '进项'}" \
                          f"（{s.get('count', 0)}笔）"
                else:
                    src = f"  ← 科目 {'/'.join(s.get('accounts') or [])}"
            print(f"         {d['label']:<32s} {d['amount']:>14s}{src}")
        print(f"       应纳税额 = {snap['result']}")
        if snap.get("note"):
            print(f"       备注：{snap['note']}")

    # ---- 4. 申报日历汇总 ----
    if items:
        # 取第一条的截止日所在月做日历
        first_due = items[0]["due_date"] or ""
        month = first_due[:7] if first_due else PERIOD
        cal = call("GET", f"/api/v1/tax/calendar?month={month}")
        st = cal["stats"]
        print(f"\n[4] 申报日历（{month}，按截止日）")
        print(f"    共 {st['total']} 项：逾期 {st.get('overdue', 0)} / "
              f"待申报 {st.get('pending', 0)} / 准备中 {st.get('preparing', 0)} / "
              f"已申报 {st.get('submitted', 0)} / 已缴款 {st.get('paid', 0)} / "
              f"免税 {st.get('exempt', 0)}")
        for day in sorted(cal["days"]):
            lst = cal["days"][day]
            print(f"    {day}：{len(lst)} 项 → " + ", ".join(
                f"{x['book_name']}·{KIND_LABEL.get(x['tax_kind'], x['tax_kind'])}"
                f"（{STATE_LABEL.get(x['state'], x['state'])}"
                f"{'·逾期' if x['overdue'] else ''}）" for x in lst))

    # ---- 5. 官网链接 ----
    links = call("GET", "/api/v1/tax/links")["links"]
    print("\n[5] 官网直达（系统不做自动申报，只做导航）")
    for k, v in links.items():
        print(f"    {KIND_LABEL.get(k, k):<12s} {v['name']}  {v['url']}")


if __name__ == "__main__":
    main()
