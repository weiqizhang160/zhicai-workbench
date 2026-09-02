# -*- coding: utf-8 -*-
"""Odoo 风格 search domain 解析器（项目书 5.3.3）——所有列表查询的地基。

语法：前缀逻辑操作符 + 叶子元组，叶子为 [field, operator, value]。
示例：
    ["&", ["state", "=", "posted"], ["date", ">=", "2026-01-01"]]
    [["name", "ilike", "科技"], ["active", "=", true]]      # 并列叶子默认 AND
    ["|", ["code", "=", "C001"], ["code", "=", "C002"]]
    ["!", ["state", "=", "draft"]]
    ["amount", "in", [100, 200]]
    ["date", "between", ["2026-01-01", "2026-06-30"]]

支持的运算符：= != > >= < <= ilike in between
逻辑连接：& (and，显式) | (or) ! (not)；并列叶子隐式 AND。
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, not_, or_
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import (
    BOOLEAN,
    DATE,
    DATETIME,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
)

from .errors import DomainError

LEAF_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "ilike", "in", "between"}
LOGIC_TOKENS = {"&", "|", "!"}

# 用于识别叶子：三元素且第二元素是合法运算符
_OP_RE = re.compile(r"^(=|!=|>=|<=|>|<|ilike|in|between)$")


def _coerce_value(col, op: str, value):
    """按列类型把 JSON 送来的值转成 Python 类型（字符串日期 → date 等）。"""
    col_type = type(col.type)
    if value is None:
        return None
    # between / in 的值是列表，逐项转换
    if op == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise DomainError("between 的值必须是两个元素的列表")
        return [_coerce_scalar(col, v) for v in value]
    if op == "in":
        if not isinstance(value, list):
            raise DomainError("in 的值必须是列表")
        return [_coerce_scalar(col, v) for v in value]
    return _coerce_scalar(col, value)


def _coerce_scalar(col, value):
    col_type = type(col.type)
    if col_type in (Date,):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return date.fromisoformat(str(value)[:10])
    if col_type in (DateTime, DATETIME):
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))
    if col_type in (Integer, BigInteger):
        return int(value)
    if col_type in (Float,):
        return float(value)
    if col_type in (Numeric,):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise DomainError(f"数值格式错误：{value!r}")
    if col_type in (Boolean, BOOLEAN):
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes")
    return value


def _leaf_to_clause(model, leaf) -> ColumnElement:
    """把 [field, op, value] 转成 SQLAlchemy 条件。"""
    if not (isinstance(leaf, (list, tuple)) and len(leaf) == 3 and _OP_RE.match(str(leaf[1]))):
        raise DomainError(f"非法的筛选叶子：{leaf!r}（应为 [字段, 运算符, 值]）")
    field_name, op, raw_value = leaf[0], str(leaf[1]), leaf[2]
    if field_name not in model.__table__.columns:
        raise DomainError(f"字段不存在：{field_name}")
    col = model.__table__.columns[field_name]
    value = _coerce_value(col, op, raw_value)

    if op == "=":
        return col.is_(None) if value is None else col == value
    if op == "!=":
        return col.is_not(None) if value is None else col != value
    if op == ">":
        return col > value
    if op == ">=":
        return col >= value
    if op == "<":
        return col < value
    if op == "<=":
        return col <= value
    if op == "ilike":
        if value is None:
            raise DomainError("ilike 的值不能为空")
        return col.ilike(f"%{value}%")
    if op == "in":
        if not value:
            # in 空列表 = 恒假（SQLAlchemy in_([]) 会告警，直接返回假条件）
            from sqlalchemy import false
            return false()
        return col.in_(value)
    if op == "between":
        return and_(col >= value[0], col <= value[1])
    raise DomainError(f"不支持的运算符：{op}")


def parse_domain(domain, model) -> ColumnElement | None:
    """解析 domain 为 SQLAlchemy where 子句。

    Odoo 语义：逻辑操作符为前缀式，作用于其后紧跟的子表达式（&/| 各消费 2 个，! 消耗 1 个）；
    顶层多个表达式隐式 AND。domain 为 None/[] 时返回 None（不过滤）。
    """
    if domain is None:
        return None
    if not isinstance(domain, list):
        raise DomainError("domain 必须是列表")
    if not domain:
        return None

    tokens = domain
    pos = 0

    def parse_expr() -> ColumnElement:
        nonlocal pos
        if pos >= len(tokens):
            raise DomainError("表达式不完整（逻辑操作符缺少操作数）")
        token = tokens[pos]
        if isinstance(token, str) and token in LOGIC_TOKENS:
            pos += 1
            if token == "!":
                return not_(parse_expr())
            left = parse_expr()
            right = parse_expr()
            return and_(left, right) if token == "&" else or_(left, right)
        leaf = token
        pos += 1
        return _leaf_to_clause(model, leaf)

    clauses = []
    while pos < len(tokens):
        clauses.append(parse_expr())
    if not clauses:
        return None
    return and_(*clauses)
