# -*- coding: utf-8 -*-
"""M6 测试：外贸专区 + 工资社保 + 文档中心（项目书 7.10 / 7.11 / 7.12 DoD）。

DoD 对照：
7.10 - 非外贸账套看不到外贸菜单；报关单-收汇关联正确显示未收汇差额
7.11 - 个税计算（3 档税率边界值）；批次确认后凭证自动生成且平衡
7.12 - 上传 10MB 内文件正常；从发票页上传后文档中心可反查来源单据
"""
import uuid
from contextlib import contextmanager
from decimal import Decimal

from fastapi.testclient import TestClient


@contextmanager
def _new_env(ft: bool = False):
    """新建一个账套并登录切换（ft=True 建外贸账套）。"""
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"login": "admin", "password": "admin123"})
        assert r.status_code == 200
        uid = uuid.uuid4().hex[:8]
        r = c.post("/api/v1/biz/books", json={
            "name": f"M6测试公司{uid}", "short_name": f"M6{uid}",
            "credit_no": f"91{uid}M6X", "taxpayer_type": "small",
            "accounting_standard": "small", "is_foreign_trade": ft,
        })
        assert r.status_code == 200, r.text
        book_id = r.json()["book"]["id"]
        c.put(f"/api/v1/biz/books/{book_id}/switch")
        yield {"c": c, "book_id": book_id, "uid": uid}


# ==================== 7.10 外贸专区 ====================

class TestForeignTradeMenu:
    """DoD：非外贸账套看不到外贸菜单。"""

    def test_menu_appears_only_with_ft_book(self):
        """有外贸账套（种子自带演示外贸客户）→ 菜单出现外贸专区。"""
        with _new_env(ft=False) as e:
            menus = e["c"].get("/api/v1/meta/menu").json()["menus"]
            ft_menus = [m for m in menus if m.get("foreign_only")]
            assert len(ft_menus) == 1 and ft_menus[0]["label"] == "外贸台账"

    def test_menu_hidden_when_no_ft_book(self):
        """全部外贸账套归档后 → 外贸菜单消失（结束后恢复原状）。"""
        from sqlalchemy import select

        from app.core.db import SessionLocal
        from app.modules.res_partner.models import ResBook

        db = SessionLocal()
        saved = []
        try:
            for b in db.execute(
                    select(ResBook).where(ResBook.is_foreign_trade.is_(True))).scalars():
                saved.append((b.id, b.active))
                b.active = False
            db.commit()

            with _new_env(ft=False) as e:
                menus = e["c"].get("/api/v1/meta/menu").json()["menus"]
                assert not any(m.get("foreign_only") for m in menus), \
                    "无外贸客户时不应显示外贸菜单"
        finally:
            for bid, active in saved:
                b = db.get(ResBook, bid)
                if b is not None:
                    b.active = active
            db.commit()
            db.close()


class TestCustomsDecl:

    def test_non_ft_book_rejected(self):
        """普通账套登记报关单 → 400 not_foreign_trade。"""
        with _new_env(ft=False) as e:
            r = e["c"].post("/api/v1/ft/decls", json={
                "decl_no": "D" + "1" * 17, "export_date": "2026-08-01",
                "usd_amount": "1000"})
            assert r.status_code == 400
            assert r.json()["code"] == "not_foreign_trade"

    def test_decl_receipt_unreceived(self):
        """DoD：报关单-收汇关联正确显示未收汇差额。"""
        with _new_env(ft=True) as e:
            c, book_id = e["c"], e["book_id"]
            r = c.post("/api/v1/ft/decls", json={
                "decl_no": "D2026080100" + e["uid"], "export_date": "2026-08-01",
                "usd_amount": "10000", "fx_rate": "7.1",
                "lines": [{"goods_name": "五金件", "qty": "100", "unit_price": "100",
                           "amount": "10000"}],
            })
            assert r.status_code == 200, r.text
            decl = r.json()["decl"]
            assert Decimal(decl["usd_amount"]) == Decimal("10000.00")
            assert Decimal(decl["unreceived"]) == Decimal("10000.00")

            # 收汇 4000（分两笔）
            r = c.post("/api/v1/ft/fx-receipts", json={
                "receipt_date": "2026-08-15", "amount": "2500", "fx_rate": "7.1",
                "decl_id": decl["id"]})
            assert r.status_code == 200, r.text
            r = c.post("/api/v1/ft/fx-receipts", json={
                "receipt_date": "2026-08-20", "amount": "1500", "fx_rate": "7.1",
                "decl_id": decl["id"], "kind": "verification"})
            assert r.status_code == 200, r.text

            detail = c.get(f"/api/v1/ft/decls/{decl['id']}").json()["decl"]
            assert Decimal(detail["received_amount"]) == Decimal("4000.00")
            assert Decimal(detail["unreceived"]) == Decimal("6000.00")
            assert len(detail["lines"]) == 1

    def test_csv_import_idempotent(self):
        """单一窗口 CSV 导入：重复导入跳过（幂等）。"""
        with _new_env(ft=True) as e:
            c = e["c"]
            rows = [
                ["报关单号", "出口日期", "成交方式", "币制", "汇率", "总价", "境外客户", "件数"],
                ["D" + e["uid"] + "01", "2026-08-01", "FOB", "USD", "7.1", "5000", "ACME Corp", "10"],
                ["D" + e["uid"] + "02", "2026-08-02", "CIF", "USD", "7.1", "3000", "Beta Ltd", "5"],
            ]
            r = c.post("/api/v1/ft/decls/import-commit", json={"rows": rows})
            assert r.status_code == 200, r.text
            assert r.json()["created"] == 2 and r.json()["skipped"] == 0

            r2 = c.post("/api/v1/ft/decls/import-commit", json={"rows": rows})
            assert r2.status_code == 200
            assert r2.json()["created"] == 0 and r2.json()["skipped"] == 2

    def test_refund_flow(self):
        """退税状态流转 collecting → received（到账需日期）。"""
        with _new_env(ft=True) as e:
            c = e["c"]
            decl = c.post("/api/v1/ft/decls", json={
                "decl_no": "DR" + e["uid"], "export_date": "2026-07-01",
                "usd_amount": "8000"}).json()["decl"]
            refund = c.post("/api/v1/ft/refunds", json={
                "decl_id": decl["id"], "period": "2026-08",
                "refund_amount": "1040"}).json()["refund"]
            assert refund["status"] == "collecting"
            for status in ("submitted", "approved", "received"):
                r = c.post(f"/api/v1/ft/refunds/{refund['id']}/status",
                           json={"status": status,
                                 "received_date": "2026-09-01" if status == "received" else None})
                assert r.status_code == 200, r.text
            got = c.get("/api/v1/ft/refunds").json()["items"][0]
            assert got["status"] == "received" and got["received_date"] == "2026-09-01"

    def test_platform_links(self):
        with _new_env(ft=True) as e:
            r = e["c"].get("/api/v1/ft/platform")
            assert r.status_code == 200
            links = r.json()["links"]
            assert "single_window" in links and links["single_window"]["url"]
            r = e["c"].put("/api/v1/ft/platform/notes", json={"notes": "法人卡登录"})
            assert r.status_code == 200
            assert e["c"].get("/api/v1/ft/platform").json()["notes"] == "法人卡登录"


# ==================== 7.11 工资社保 ====================

class TestIIT:
    """DoD：个税计算单测（3 档税率边界值）。"""

    def test_below_threshold(self):
        """应发 ≤ 5000+社保 → 不征税。"""
        from app.modules.payroll.iit import compute_iit_monthly
        assert compute_iit_monthly("5000", "0") == Decimal("0.00")
        assert compute_iit_monthly("4000", "800") == Decimal("0.00")

    def test_bracket_boundaries(self):
        from app.modules.payroll.iit import compute_iit_monthly
        # 应纳税所得额 3000（3% 档上限）：8000 - 5000 = 3000 → 90.00
        assert compute_iit_monthly("8000", "0") == Decimal("90.00")
        # 3001（跨入 10% 档）：3001×10% − 210 = 90.10
        assert compute_iit_monthly("8001", "0") == Decimal("90.10")
        # 12000（10% 档上限）：17000-5000=12000 → 12000×10%−210 = 990.00
        assert compute_iit_monthly("17000", "0") == Decimal("990.00")
        # 12001（跨入 20% 档）：12001×20%−1410 = 990.20
        assert compute_iit_monthly("17001", "0") == Decimal("990.20")
        # 25000（20% 档上限）：30000-5000 → 25000×20%−1410 = 3590.00
        assert compute_iit_monthly("30000", "0") == Decimal("3590.00")

    def test_social_deducted(self):
        """个人社保先于起征点扣除。"""
        from app.modules.payroll.iit import compute_iit_monthly
        # (10000-5000-1500)=3500 → 3500×10%−210 = 140.00
        assert compute_iit_monthly("10000", "1500") == Decimal("140.00")

    def test_cumulative(self):
        """累计预扣法：累计口径换算（月表 ×12）。"""
        from app.modules.payroll.iit import compute_iit_cumulative
        # 2 个月累计应纳税所得额 2×3000=6000（年度表 36000 内 3%…月表 3000×12=36000）
        # 6000×3% = 180；首月已预扣 90 → 本期 90
        v = compute_iit_cumulative("16000", "0", "90", months=2)
        assert v == Decimal("90.00")


class TestPayrollBatch:

    def test_batch_lifecycle_and_moves(self):
        """DoD：批次确认后凭证自动生成且平衡。"""
        with _new_env() as e:
            c, book_id = e["c"], e["book_id"]
            batch = c.post("/api/v1/payroll/batches", json={"period": "2026-08"}).json()["batch"]
            assert batch["state"] == "draft"

            # 两名员工
            for name, gross, social in (("张三", "10000", "1500"), ("李四", "6500", "800")):
                r = c.post(f"/api/v1/payroll/batches/{batch['id']}/lines", json={
                    "employee_name": name, "gross_salary": gross,
                    "social_employee": social, "social_employer": "3500",
                    "fund_employer": "1000"})
                assert r.status_code == 200, r.text

            # 个税自动算：张三 140.00（见 TestIIT），李四 (6500-5000-800)=700×3%=21
            detail = c.get(f"/api/v1/payroll/batches/{batch['id']}").json()["batch"]
            lines = {ln["employee_name"]: ln for ln in detail["lines"]}
            assert lines["张三"]["iit"] == "140.00"
            assert lines["李四"]["iit"] == "21.00"
            # 实发 = 应发 − 个人社保 − 个税
            assert lines["张三"]["net_salary"] == "8360.00"
            assert lines["李四"]["net_salary"] == "5679.00"
            # 批次合计
            assert detail["employee_count"] == 2
            assert Decimal(detail["total_gross"]) == Decimal("16500.00")

            # 同期间重复建批次 → 拒绝
            r = c.post("/api/v1/payroll/batches", json={"period": "2026-08"})
            assert r.status_code == 400

            # 复制上月：先确认本月，再建 9 月批次复制
            r = c.post(f"/api/v1/payroll/batches/{batch['id']}/confirm")
            assert r.status_code == 200, r.text
            confirmed = r.json()["batch"]
            assert confirmed["state"] == "confirmed"
            assert confirmed["accrual_move_id"] and confirmed["payment_move_id"]

            # 凭证平衡校验（过账前置校验在记账模块，这里直接查分录合计）
            from app.core.db import SessionLocal
            from app.modules.account.models import AccountMoveLine
            db = SessionLocal()
            try:
                for move_id in (confirmed["accrual_move_id"], confirmed["payment_move_id"]):
                    mvs = db.execute(
                        AccountMoveLine.__table__.select().where(
                            AccountMoveLine.move_id == move_id)
                    ).mappings().all()
                    debit = sum((Decimal(str(m["debit"])) for m in mvs), Decimal("0"))
                    credit = sum((Decimal(str(m["credit"])) for m in mvs), Decimal("0"))
                    assert debit == credit and debit > 0, (move_id, debit, credit)
            finally:
                db.close()

            # 复制上月
            r = c.post("/api/v1/payroll/batches",
                       json={"period": "2026-09", "copy_from_last": True})
            assert r.status_code == 200, r.text
            sep = r.json()["batch"]
            assert sep["employee_count"] == 2, "应复制上月 2 名员工"

            # 已确认批次不可改员工行
            r = c.post(f"/api/v1/payroll/batches/{batch['id']}/lines",
                       json={"employee_name": "王五", "gross_salary": "5000"})
            assert r.status_code == 400

            # 标记发放
            r = c.post(f"/api/v1/payroll/batches/{batch['id']}/mark-paid")
            assert r.status_code == 200
            assert r.json()["batch"]["state"] == "paid"

    def test_iit_preview_endpoint(self):
        with _new_env() as e:
            r = e["c"].get("/api/v1/payroll/iit/preview",
                           params={"gross": "8001", "social_employee": "0"})
            assert r.status_code == 200
            assert r.json()["iit"] == "90.10"


# ==================== 7.12 文档中心 ====================

PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


class TestDocuments:

    def test_upload_list_preview(self):
        """上传 → 跨账套列表 → 在线预览（PDF MIME）。"""
        with _new_env() as e1:
            c1, book1 = e1["c"], e1["book_id"]
            r = c1.post("/api/v1/docs/upload",
                        files=[("files", ("营业执照.pdf", PDF_BYTES, "application/pdf"))],
                        data={"book_id": str(book1), "doc_type": "license",
                              "tags": "证照,工商", "doc_year": "2026"})
            assert r.status_code == 200, r.text
            rec = r.json()["records"][0]
            assert rec["doc_type"] == "license" and rec["previewable"]

            # 跨账套列表：另一个账套也能看到（总览模式）
            with _new_env() as e2:
                r = e2["c"].get("/api/v1/docs", params={"doc_type": "license"})
                records = r.json()["records"]
                assert any(x["id"] == rec["id"] for x in records), "跨账套列表应可见"

                # 筛选：标签 + 年份
                r = e2["c"].get("/api/v1/docs", params={"tag": "证照", "year": 2026})
                assert any(x["id"] == rec["id"] for x in r.json()["records"])
                r = e2["c"].get("/api/v1/docs", params={"tag": "证照", "year": 2025})
                assert not any(x["id"] == rec["id"] for x in r.json()["records"])

            # 在线预览：PDF 返回 application/pdf
            r = c1.get(f"/api/v1/docs/{rec['id']}/file")
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("application/pdf")

            # 元数据编辑 + 软删除
            r = c1.put(f"/api/v1/docs/{rec['id']}", json={
                "values": {"tags": "证照", "remark": "2026 年新版"}})
            assert r.status_code == 200
            r = c1.delete(f"/api/v1/docs/{rec['id']}")
            assert r.status_code == 200
            assert c1.get(f"/api/v1/docs/{rec['id']}").status_code == 400

    def test_upload_multi_files_and_size_limit(self):
        with _new_env() as e:
            c, book_id = e["c"], e["book_id"]
            # 多文件一次上传
            r = c.post("/api/v1/docs/upload", files=[
                ("files", ("回单1.pdf", PDF_BYTES, "application/pdf")),
                ("files", ("回单2.pdf", PDF_BYTES, "application/pdf")),
            ], data={"book_id": str(book_id), "doc_type": "bank_slip"})
            assert r.status_code == 200, r.text
            assert r.json()["count"] == 2
            names = {x["name"] for x in r.json()["records"]}
            assert names == {"回单1", "回单2"}

            # 超 10MB 拒绝
            big = b"x" * (10 * 1024 * 1024 + 1)
            r = c.post("/api/v1/docs/upload",
                       files=[("files", ("big.bin", big, "application/octet-stream"))],
                       data={"book_id": str(book_id)})
            assert r.status_code == 400
            assert r.json()["code"] == "file_too_large"

            # 不支持的扩展名拒绝
            r = c.post("/api/v1/docs/upload",
                       files=[("files", ("evil.exe", b"MZ", "application/octet-stream"))],
                       data={"book_id": str(book_id)})
            assert r.status_code == 400
            assert r.json()["code"] == "bad_ext"

    def test_invoice_upload_reverse_lookup(self):
        """DoD：从发票页上传影像后，文档中心可反查来源单据。"""
        with _new_env() as e:
            c, book_id = e["c"], e["book_id"]
            inv = c.post("/api/v1/inv/bills", json={
                "direction": "input", "invoice_no": "INV" + e["uid"],
                "invoice_date": "2026-08-01", "partner_name": "供应商甲",
                "goods_amount": "1000", "tax_amount": "130",
                "total_amount": "1130", "tax_rate": "0.13"}).json()["invoice"]

            r = c.post(f"/api/v1/inv/bills/{inv['id']}/attachment",
                       files={"file": ("scan.jpg", b"\xff\xd8\xff\xe0fakejpg", "image/jpeg")})
            assert r.status_code == 200, r.text

            # 文档中心反查
            r = c.get(f"/api/v1/docs/by-source/invoice_bill/{inv['id']}")
            assert r.status_code == 200
            records = r.json()["records"]
            assert len(records) == 1
            assert records[0]["source_model"] == "invoice_bill"
            assert records[0]["source_id"] == inv["id"]
            assert records[0]["doc_type"] == "invoice"
            assert records[0]["book_id"] == book_id
