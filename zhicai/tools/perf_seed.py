# -*- coding: utf-8 -*-
"""M7 性能压测（项目书 2.3 / 9 章 / M7 验收）：

  1) 造数据：100 账套 × 10 年 × 每月 40 张凭证（≈48 万凭证 + 192 万分录行，
     对齐项目书 2.3 的 10 年累计估算），写入独立库 data/perf.db（不动生产库）；
  2) 核查索引：account_move / account_move_line 的 book_id、date、account_id 关键路径；
  3) 压接口：凭证列表 / 分录列表 / 科目余额表（10 年）/ 资产负债表 / 利润表 / 仪表盘，
     每项跑 N 次取 P50/P95，对照验收线（列表 P95<300ms、仪表盘<1s）。

用法（在 zhicai/ 目录下）：
  .venv/Scripts/python.exe tools/perf_seed.py                 # 造数据 + 压测
  .venv/Scripts/python.exe tools/perf_seed.py --fresh         # 删掉 perf.db 重造
  .venv/Scripts/python.exe tools/perf_seed.py --test-only     # 只压测（数据已存在）
  .venv/Scripts/python.exe tools/perf_seed.py --books 20 --years 3   # 缩小规模快速验证
"""
import argparse
import os
import sqlite3
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # zhicai/
PERF_DB = ROOT / "data" / "perf.db"

ap = argparse.ArgumentParser()
ap.add_argument("--books", type=int, default=100)
ap.add_argument("--years", type=int, default=10)
ap.add_argument("--moves-per-month", type=int, default=40, help="每账套每月凭证数（项目书 2.3：40）")
ap.add_argument("--runs", type=int, default=20, help="每个接口压测次数")
ap.add_argument("--fresh", action="store_true", help="删除 perf.db 重新造数据")
ap.add_argument("--seed-only", action="store_true")
ap.add_argument("--test-only", action="store_true")
args = ap.parse_args()

# —— 必须在 import app 之前设置环境（引擎按此建连接）——
os.environ["ZC_DB_PATH"] = str(PERF_DB)
os.environ["ZC_DISABLE_SCHEDULER"] = "1"

sys.path.insert(0, str(ROOT))


def months_of(years: int) -> list[tuple[str, date]]:
    """最近 N 年的 (period, 日期基准) 列表。"""
    today = date.today()
    start = date(today.year - years + 1, 1, 1)
    out = []
    y, m = start.year, start.month
    while (y, m) <= (today.year, today.month):
        out.append((f"{y:04d}-{m:02d}", date(y, m, 1)))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


# ==================== 造数据 ====================

def seed_data() -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.db import SessionLocal
    from app.modules.res_partner.service import create_book
    from sqlalchemy import text

    t0 = time.time()
    with TestClient(app) as c:  # 触发 lifespan：建表 + 种子
        assert c.post("/api/v1/auth/login",
                      json={"login": "admin", "password": "admin123"}).status_code == 200
    print(f"[1/3] 建表与种子完成（{time.time() - t0:.1f}s）")

    # —— 100 个账套（含科目表/账簿初始化）——
    t0 = time.time()
    db = SessionLocal()
    book_ids = []
    try:
        n_exist = db.execute(text("SELECT COUNT(*) FROM res_book")).scalar_one()
        if n_exist < args.books:
            for i in range(n_exist, args.books):
                b = create_book(db, {
                    "name": f"压测客户{i + 1:03d}有限公司",
                    "short_name": f"压测{i + 1:03d}",
                    "taxpayer_type": "general" if i % 3 == 0 else "small",
                    "bookkeeping_start": f"{date.today().year - args.years + 1}-01-01",
                }, 1)
                book_ids.append(b.id)
                if len(book_ids) % 20 == 0:
                    db.commit()
            db.commit()
        else:
            book_ids = [r[0] for r in db.execute(
                text("SELECT id FROM res_book ORDER BY id")).all()]
    finally:
        db.close()
    print(f"[2/3] {len(book_ids)} 个账套就绪（{time.time() - t0:.1f}s）")

    # —— 批量造凭证：直接 SQL executemany（绕过 ORM，纯插入速度）——
    t0 = time.time()
    conn = sqlite3.connect(str(PERF_DB))
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    months = months_of(args.years)
    now_iso = date.today().isoformat() + " 00:00:00"

    move_cols = ("id, journal_id, move_date, period, state, source_type, attachment_count, "
                 "is_template, book_id, name, create_uid, create_date, write_uid, write_date, active")
    line_cols = ("id, move_id, line_no, summary, account_id, debit, credit, book_id, "
                 "create_uid, create_date, write_uid, write_date, active")

    move_id = cur.execute("SELECT COALESCE(MAX(id), 0) FROM account_move").fetchone()[0]
    line_id = cur.execute("SELECT COALESCE(MAX(id), 0) FROM account_move_line").fetchone()[0]
    total_moves = total_lines = 0

    for bi, bid in enumerate(book_ids):
        # 每账套取 4 个常用末级科目：1002 银行 / 6602 费用 / 6001 收入 / 2202 应付
        accts = {p: None for p in ("1002", "6602", "6001", "2202")}
        for aid, code in cur.execute(
                "SELECT id, code FROM account_account WHERE book_id=? AND active=1", (bid,)):
            for p in accts:
                if code == p or code.startswith(p + "."):
                    accts[p] = aid  # 后者覆盖前者 → 取到最末级
        journal = cur.execute(
            "SELECT id FROM account_journal WHERE book_id=? LIMIT 1", (bid,)).fetchone()
        if not journal or any(v is None for v in accts.values()):
            continue
        jid = journal[0]

        moves, lines = [], []
        seq = 0
        for period, base_day in months:
            for k in range(args.moves_per_month):
                seq += 1
                move_id += 1
                mdate = base_day + timedelta(days=min(k, 27) % 28)
                amount = 1000 + (seq % 900)
                expense = 50 + (seq % 400)
                moves.append((
                    move_id, jid, mdate.isoformat(), period, "posted", "manual", 0, 0,
                    bid, f"压{seq:07d}", 1, now_iso, 1, now_iso, 1,
                ))
                # 4 行平衡分录：借银行 / 借费用 / 贷收入 / 贷应付
                for line_no, (acct, dr, cr) in enumerate([
                        (accts["1002"], amount, 0),
                        (accts["6602"], expense, 0),
                        (accts["6001"], 0, amount),
                        (accts["2202"], 0, expense)], start=1):
                    line_id += 1
                    lines.append((
                        line_id, move_id, line_no, "性能压测造数", acct,
                        f"{dr}.00", f"{cr}.00", bid, 1, now_iso, 1, now_iso, 1,
                    ))
        cur.executemany(f"INSERT INTO account_move ({move_cols}) "
                        f"VALUES ({','.join('?' * 15)})", moves)
        cur.executemany(f"INSERT INTO account_move_line ({line_cols}) "
                        f"VALUES ({','.join('?' * 13)})", lines)
        conn.commit()
        total_moves += len(moves)
        total_lines += len(lines)
        if (bi + 1) % 20 == 0:
            print(f"    ... {bi + 1}/{len(book_ids)} 账套，累计 {total_moves} 凭证 / {total_lines} 行"
                  f"（{time.time() - t0:.0f}s）")

    conn.commit()
    conn.close()
    print(f"[3/3] 造数完成：{total_moves} 张凭证 / {total_lines} 行分录（{time.time() - t0:.1f}s），"
          f"库文件 {PERF_DB.stat().st_size / 1024 / 1024:.0f} MB")


# ==================== 索引核查 ====================

def check_indexes() -> bool:
    conn = sqlite3.connect(str(PERF_DB))
    cur = conn.cursor()
    print("\n===== 索引核查（关键查询路径 book_id / date / account_id）=====")
    ok = True
    for table, need_cols in [
        ("account_move", {"book_id", "move_date", "period", "state"}),
        ("account_move_line", {"book_id", "move_id", "account_id"}),
        ("invoice_bill", {"book_id", "period"}),
        ("bank_statement_line", {"book_id"}),
    ]:
        cols = set()
        for idx in cur.execute(f"PRAGMA index_list({table})").fetchall():
            for info in cur.execute(f"PRAGMA index_info({idx[1]})").fetchall():
                cols.add(info[2])
        missing = need_cols - cols
        status = "OK" if not missing else f"缺 {missing}"
        if missing:
            ok = False
        print(f"  {table:22s} 索引列: {sorted(cols)}  -> {status}")
    conn.close()
    return ok


# ==================== 接口压测 ====================

def run_tests() -> int:
    from fastapi.testclient import TestClient
    from app.main import app

    today = date.today()
    start_period = f"{today.year - args.years + 1:04d}-01"
    end_period = f"{today.year:04d}-{today.month:02d}"

    with TestClient(app) as c:
        assert c.post("/api/v1/auth/login",
                      json={"login": "admin", "password": "admin123"}).status_code == 200
        # 切到第一个压测账套（列表/账簿/报表都是账套内查询）
        books = c.get("/api/v1/biz/books").json()["books"]
        perf_book = next((b["id"] for b in books if b["short_name"].startswith("压测")),
                         books[0]["id"])
        assert c.put(f"/api/v1/biz/books/{perf_book}/switch").status_code == 200

        # 数据量自检
        conn = sqlite3.connect(str(PERF_DB))
        n_moves = conn.execute("SELECT COUNT(*) FROM account_move").fetchone()[0]
        n_lines = conn.execute("SELECT COUNT(*) FROM account_move_line").fetchone()[0]
        conn.close()
        print(f"\n===== 压测目标账套 #{perf_book}，全库 {n_moves} 凭证 / {n_lines} 分录行 =====")

        cases = [
            ("凭证列表（账套过滤+排序）",
             f"/api/v1/data/account_move?limit=80&order=move_date desc,id desc", 300),
            ("分录行列表（账套过滤）",
             "/api/v1/data/account_move_line?limit=80&order=id desc", 300),
            ("往来单位列表",
             "/api/v1/data/res_partner?limit=80", 300),
            (f"科目余额表（{start_period}~{end_period}）",
             f"/api/v1/acc/ledger/trial?period_from={start_period}&period_to={end_period}", 300),
            ("资产负债表（最新期间）",
             f"/api/v1/acc/report/balance-sheet?period={end_period}", 300),
            (f"利润表（{start_period}~{end_period}）",
             f"/api/v1/acc/report/income?period_from={start_period}&period_to={end_period}", 300),
            ("仪表盘汇总（跨账套）",
             "/api/v1/dashboard/summary", 1000),
        ]

        print(f"\n===== 接口压测（每项 {args.runs} 次）=====")
        failures = 0
        for label, url, budget_ms in cases:
            lat = []
            for _ in range(args.runs):
                t0 = time.perf_counter()
                r = c.get(url)
                lat.append((time.perf_counter() - t0) * 1000)
                if r.status_code != 200:
                    print(f"  ✗ {label}：HTTP {r.status_code} {r.text[:120]}")
                    failures += 1
                    break
            else:
                lat.sort()
                p50 = statistics.median(lat)
                p95 = lat[max(0, int(len(lat) * 0.95) - 1)]
                ok = p95 < budget_ms
                if not ok:
                    failures += 1
                print(f"  {'PASS' if ok else 'FAIL'}  {label:<24s} P50={p50:7.1f}ms  "
                      f"P95={p95:7.1f}ms  max={lat[-1]:7.1f}ms  预算<{budget_ms}ms")
        print(f"\n===== 结论：{'全部达标' if failures == 0 else str(failures) + ' 项超预算'} =====")
        return failures


if __name__ == "__main__":
    if not args.test_only:
        if args.fresh:
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(PERF_DB) + suffix)
                if p.exists():
                    p.unlink()
        seed_data()
    if not args.seed_only:
        idx_ok = check_indexes()
        fail = run_tests()
        sys.exit(0 if (fail == 0 and idx_ok) else 1)
