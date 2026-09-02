# -*- coding: utf-8 -*-
"""CRUD API / 认证 / 新建客户向导 / 审计 / 账套隔离 集成测试（M1 验收标准 ⑥）。"""
import json


# ---------- 认证 ----------
class TestAuth:
    def test_me_logged_in(self, client):
        r = client.get("/api/v1/auth/me")
        assert r.status_code == 200
        assert r.json()["user"]["login"] == "admin"
        assert r.json()["user"]["role_code"] == "admin"

    def test_me_anonymous(self, fresh_client):
        r = fresh_client.get("/api/v1/auth/me")
        assert r.status_code == 200
        assert r.json()["user"] is None

    def test_unauthorized_blocked(self, fresh_client):
        r = fresh_client.get("/api/v1/data/res_book")
        assert r.status_code == 401

    def test_wrong_password(self, fresh_client):
        r = fresh_client.post("/api/v1/auth/login", json={"login": "admin", "password": "wrong"})
        assert r.status_code == 400

    def test_change_password_flow(self, fresh_client):
        r = fresh_client.post("/api/v1/auth/login", json={"login": "admin", "password": "admin123"})
        assert r.status_code == 200
        # 改密码 → 旧密码失效 → 新密码可登录 → 改回（保持测试库稳定）
        r = fresh_client.put("/api/v1/auth/password",
                             json={"old_password": "admin123", "new_password": "newpass123"})
        assert r.status_code == 200
        r = fresh_client.post("/api/v1/auth/login", json={"login": "admin", "password": "admin123"})
        assert r.status_code == 400
        r = fresh_client.post("/api/v1/auth/login", json={"login": "admin", "password": "newpass123"})
        assert r.status_code == 200
        r = fresh_client.put("/api/v1/auth/password",
                             json={"old_password": "newpass123", "new_password": "admin123"})
        assert r.status_code == 200


# ---------- meta ----------
class TestMeta:
    def test_menu(self, client):
        r = client.get("/api/v1/meta/menu")
        labels = [m["label"] for m in r.json()["menus"]]
        assert "客户管理" in labels and "会计科目" in labels and "用户管理" in labels

    def test_describe_res_book(self, client):
        r = client.get("/api/v1/meta/res_book")
        d = r.json()
        assert d["table"] == "res_book"
        assert d["fields"]["taxpayer_type"]["type"] == "selection"
        assert d["fields"]["taxpayer_type"]["options"][0]["value"] == "general"
        assert d["views"]["list"]["fields"][0] == "code"

    def test_describe_unknown_404_like(self, client):
        r = client.get("/api/v1/meta/no_such_table")
        assert r.status_code == 400  # BizError → 400


# ---------- CRUD ----------
class TestCrud:
    def test_seed_books_exist(self, client):
        r = client.get("/api/v1/data/res_book")
        assert r.json()["total"] >= 2
        codes = [rec["code"] for rec in r.json()["records"]]
        assert "C001" in codes and "C002" in codes

    def test_list_filter_domain(self, client):
        r = client.get('/api/v1/data/res_book?domain=[["taxpayer_type", "=", "general"]]')
        assert r.status_code == 200
        for rec in r.json()["records"]:
            assert rec["taxpayer_type"] == "general"

    def test_list_search_ilike(self, client):
        r = client.get('/api/v1/data/res_book?domain=[["short_name", "ilike", "五金"]]')
        assert any("五金" in rec["short_name"] for rec in r.json()["records"])

    def test_list_order_and_paging(self, client):
        r = client.get("/api/v1/data/res_book?order=code desc&limit=1")
        recs = r.json()["records"]
        assert len(recs) == 1
        all_codes = [x["code"] for x in
                     client.get("/api/v1/data/res_book?limit=500").json()["records"]]
        assert recs[0]["code"] == max(all_codes)

    def test_create_update_partner_with_audit(self, client):
        """建往来单位 → 改字段 → 活动日志记录变更（验收标准 ④）。"""
        # 先切到 C001
        books = client.get("/api/v1/biz/books").json()["books"]
        book1 = next(b for b in books if b["code"] == "C001")
        client.put(f"/api/v1/biz/books/{book1['id']}/switch")
        # 创建
        r = client.post("/api/v1/data/res_partner",
                        json={"values": {"name": "深圳供应商A", "partner_type": "supplier",
                                         "tax_no": "91440300TEST0001"}})
        assert r.status_code == 200, r.text
        pid = r.json()["record"]["id"]
        assert r.json()["record"]["book_id"] == book1["id"]  # 账套自动注入
        # 更新
        r = client.put(f"/api/v1/data/res_partner/{pid}",
                       json={"values": {"phone": "0755-11112222"}})
        assert r.status_code == 200
        assert any(c["field"] == "phone" for c in r.json()["changes"])
        # 活动日志
        r = client.get(f"/api/v1/data/res_partner/{pid}")
        chatter = r.json()["chatter"]
        actions = [c.get("action") for c in chatter]
        assert "create" in actions and "write" in actions

    def test_note_add(self, client):
        r = client.post("/api/v1/data/res_book/1/note", json={"body": "首次拜访客户，资料已收齐"})
        assert r.status_code == 200
        assert any(c["kind"] == "note" for c in r.json()["chatter"])

    def test_soft_delete(self, client):
        books = client.get("/api/v1/biz/books").json()["books"]
        book1 = next(b for b in books if b["code"] == "C001")
        client.put(f"/api/v1/biz/books/{book1['id']}/switch")
        r = client.post("/api/v1/data/res_partner",
                        json={"values": {"name": "待删除单位B", "partner_type": "customer"}})
        pid = r.json()["record"]["id"]
        r = client.delete(f"/api/v1/data/res_partner/{pid}")
        assert r.status_code == 200
        # 列表里不可见（软删除）
        r = client.get(f"/api/v1/data/res_partner/{pid}")
        assert r.status_code == 400

    def test_create_requires_book(self, client):
        """总览模式下，非白名单模型新建必须先选账套。"""
        client.put("/api/v1/biz/books/0/switch")  # 切回总览
        r = client.post("/api/v1/data/res_partner",
                        json={"values": {"name": "无账套单位", "partner_type": "customer"}})
        assert r.status_code == 400
        assert r.json()["code"] == "book_required"


# ---------- 账套隔离 ----------
class TestBookIsolation:
    def test_scoped_model_isolated(self, client):
        """账套 A 的往来单位在账套 B 不可见（Odoo 多公司机制）。"""
        books = client.get("/api/v1/biz/books").json()["books"]
        b1 = next(b for b in books if b["code"] == "C001")
        b2 = next(b for b in books if b["code"] == "C002")
        # 在 C001 建一条
        client.put(f"/api/v1/biz/books/{b1['id']}/switch")
        r = client.post("/api/v1/data/res_partner",
                        json={"values": {"name": "隔离测试单位", "partner_type": "customer"}})
        pid = r.json()["record"]["id"]
        # 切到 C002 看不到
        client.put(f"/api/v1/biz/books/{b2['id']}/switch")
        r = client.get(f"/api/v1/data/res_partner/{pid}")
        assert r.status_code == 400  # not_found（隔离）
        # 切回 C001 可见
        client.put(f"/api/v1/biz/books/{b1['id']}/switch")
        r = client.get(f"/api/v1/data/res_partner/{pid}")
        assert r.status_code == 200

    def test_account_isolated(self, client):
        """科目表按账套隔离，两边数量一致但 id 独立。"""
        books = client.get("/api/v1/biz/books").json()["books"]
        b1 = next(b for b in books if b["code"] == "C001")
        b2 = next(b for b in books if b["code"] == "C002")
        client.put(f"/api/v1/biz/books/{b1['id']}/switch")
        total1 = client.get("/api/v1/data/account_account?count_only=true").json()["total"]
        ids1 = {r["id"] for r in client.get("/api/v1/data/account_account?limit=500").json()["records"]}
        client.put(f"/api/v1/biz/books/{b2['id']}/switch")
        total2 = client.get("/api/v1/data/account_account?count_only=true").json()["total"]
        ids2 = {r["id"] for r in client.get("/api/v1/data/account_account?limit=500").json()["records"]}
        assert total1 == total2 == 87
        assert not (ids1 & ids2)  # 无交集


# ---------- 新建客户向导（验收标准 ②） ----------
class TestCreateBookWizard:
    def test_create_book_full_init(self, client):
        """新建客户：科目表（87 个）+ 账簿（4 个）+ 编号器（4 个）一次到位。"""
        client.put("/api/v1/biz/books/0/switch")
        r = client.post("/api/v1/biz/books", json={
            "name": "深圳市测试贸易有限公司", "short_name": "测试贸易",
            "credit_no": "91440300TESTBOOK99", "taxpayer_type": "general",
            "bookkeeping_start": "2026-03-01",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["account_count"] == 87
        book_id = data["book"]["id"]
        # 切过去验证账簿与科目
        client.put(f"/api/v1/biz/books/{book_id}/switch")
        journals = client.get("/api/v1/data/account_journal").json()["records"]
        assert sorted(j["code"] for j in journals) == ["付", "收", "记", "转"]
        # 科目树：1002 银行存款是末级，2221 应交税费非末级
        accounts = client.get("/api/v1/data/account_account?limit=500").json()["records"]
        by_code = {a["code"]: a for a in accounts}
        assert by_code["1002"]["is_leaf"] is True
        assert by_code["2221"]["is_leaf"] is False
        assert by_code["2221.01"]["is_leaf"] is False
        assert by_code["2221.01.01"]["is_leaf"] is True
        # parent 关系
        assert by_code["2221.01.01"]["parent_id"] == by_code["2221.01"]["id"]

    def test_duplicate_credit_no_blocked(self, client):
        r = client.post("/api/v1/biz/books", json={
            "name": "重复税号公司", "credit_no": "91440300TESTBOOK99"})
        assert r.status_code == 400
        assert r.json()["code"] == "credit_no_dup"

    def test_name_required(self, client):
        r = client.post("/api/v1/biz/books", json={"name": "  "})
        assert r.status_code == 400


# ---------- 全局搜索 ----------
class TestSearch:
    def test_search_book(self, client):
        r = client.get("/api/v1/biz/search?q=五金")
        results = r.json()["results"]
        assert any(x["type"] == "book" for x in results)

    def test_search_min_length(self, client):
        r = client.get("/api/v1/biz/search?q=")
        assert r.status_code == 422
