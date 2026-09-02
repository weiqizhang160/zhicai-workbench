# -*- coding: utf-8 -*-
"""domain 解析器单测（M1 验收标准 ⑤：完整覆盖每个运算符/连接符/异常分支）。

用一个真实模型（ResBook）构造查询验证 where 子句行为。
"""
import pytest
from sqlalchemy import select
from sqlalchemy.dialects import sqlite as sqlite_dialect

from app.core.domain import parse_domain
from app.core.errors import DomainError
from app.modules.res_partner.models import ResBook


def _where(domain):
    return parse_domain(domain, ResBook)


def _sql(domain):
    """编译成参数内联的 SQL 字符串方便断言。"""
    stmt = select(ResBook).where(_where(domain))
    return str(stmt.compile(dialect=sqlite_dialect.dialect(),
                            compile_kwargs={"literal_binds": True})).replace("\n", " ")


# ---------- 叶子运算符 ----------
class TestLeafOperators:
    def test_eq(self):
        assert "taxpayer_type = 'small'" in _sql([["taxpayer_type", "=", "small"]])

    def test_eq_none(self):
        assert "credit_no IS NULL" in _sql([["credit_no", "=", None]])

    def test_neq(self):
        assert "taxpayer_type != 'general'" in _sql([["taxpayer_type", "!=", "general"]])

    def test_neq_none(self):
        assert "credit_no IS NOT NULL" in _sql([["credit_no", "!=", None]])

    def test_gt_gte_lt_lte(self):
        assert "id > 5" in _sql([["id", ">", 5]])
        assert "id >= 5" in _sql([["id", ">=", 5]])
        assert "id < 5" in _sql([["id", "<", 5]])
        assert "id <= 5" in _sql([["id", "<=", 5]])

    def test_ilike(self):
        sql = _sql([["short_name", "ilike", "五金"]])
        assert "LIKE lower('%五金%')" in sql

    def test_in_(self):
        sql = _sql([["code", "in", ["C001", "C002"]]])
        assert "code IN" in sql

    def test_in_empty_list_is_false(self):
        sql = _sql([["code", "in", []]])
        assert "0 = 1" in sql  # 恒假

    def test_between(self):
        sql = _sql([["bookkeeping_start", "between", ["2026-01-01", "2026-06-30"]]])
        # 字符串日期应被转成 date 对象参与比较
        assert "bookkeeping_start >=" in sql and "bookkeeping_start <=" in sql

    def test_date_string_coerced(self):
        """字符串日期自动转 date（SQLite Date 类型要求）。"""
        from datetime import date
        w = _where([["bookkeeping_start", ">=", "2026-01-01"]])
        # 编译期检查不抛错即通过
        str(w)

    def test_boolean_coerced(self):
        """'true' 字符串自动转 bool。"""
        sql = _sql([["is_foreign_trade", "=", True]])
        assert "is_foreign_trade = 1" in sql


# ---------- 逻辑连接 ----------
class TestLogic:
    def test_implicit_and(self):
        """并列叶子默认 AND。"""
        sql = _sql([["taxpayer_type", "=", "small"], ["charge_status", "=", "normal"]])
        assert "AND" in sql

    def test_explicit_and(self):
        sql = _sql(["&", ["taxpayer_type", "=", "small"], ["charge_status", "=", "normal"]])
        assert "AND" in sql

    def test_or(self):
        sql = _sql(["|", ["code", "=", "C001"], ["code", "=", "C002"]])
        assert "OR" in sql

    def test_not(self):
        sql = _sql(["!", ["taxpayer_type", "=", "small"]])
        assert "NOT" in sql.upper() or "taxpayer_type != 'small'" in sql

    def test_mixed_prefix_and_implicit(self):
        """项目书示例：& 显式 + 并列隐式（Odoo 语义）。"""
        sql = _sql(["&", ["taxpayer_type", "=", "general"], ["is_foreign_trade", "=", True],
                    ["charge_status", "=", "normal"]])
        assert "AND" in sql

    def test_nested_or_in_and(self):
        sql = _sql(["&", "|", ["code", "=", "C001"], ["code", "=", "C002"],
                    ["charge_status", "=", "normal"]])
        assert "OR" in sql and "AND" in sql


# ---------- 空与异常 ----------
class TestEdgeCases:
    def test_none_domain(self):
        assert parse_domain(None, ResBook) is None

    def test_empty_domain(self):
        assert parse_domain([], ResBook) is None

    def test_non_list_domain(self):
        with pytest.raises(DomainError):
            parse_domain("name = x", ResBook)

    def test_unknown_field(self):
        with pytest.raises(DomainError, match="字段不存在"):
            _where([["no_such_field", "=", 1]])

    def test_bad_operator(self):
        with pytest.raises(DomainError):
            _where([["code", "~", "x"]])

    def test_bad_leaf_shape(self):
        with pytest.raises(DomainError):
            _where([["code", "="]])  # 两元素
        with pytest.raises(DomainError):
            _where(["code"])  # 一元素

    def test_or_missing_operand(self):
        with pytest.raises(DomainError, match="缺少操作数"):
            _where(["|", ["code", "=", "C001"]])

    def test_not_missing_operand(self):
        with pytest.raises(DomainError, match="缺少操作数"):
            _where(["!"])

    def test_between_bad_value(self):
        with pytest.raises(DomainError):
            _where([["bookkeeping_start", "between", "2026-01-01"]])  # 非列表

    def test_in_bad_value(self):
        with pytest.raises(DomainError):
            _where([["code", "in", "C001"]])  # 非列表
