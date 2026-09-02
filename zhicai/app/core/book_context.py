# -*- coding: utf-8 -*-
"""当前账套上下文（对标 Odoo 多公司切换，项目书 5.3.5）。

- 前端顶栏账套切换器把 book_id 写入 cookie（zhicai_book，值为数字或 "all"）；
- 中间件解析 cookie → request.state.book_id；
- CRUD 层对 book_scoped 模型自动注入过滤；"all"（总览模式）仅对
  视图配置声明了 cross_book 的模型放行（对标 Odoo record rules 白名单）。
"""

ALL_BOOKS = "all"

CROSS_BOOK_ALLOWED = {"res_book"}  # M1 总览白名单：客户列表本身跨账套


def get_book_id(request) -> int | str | None:
    """从 request.state 取当前账套；未携带则读 cookie。"""
    v = getattr(request.state, "book_id", None)
    if v is not None:
        return v
    raw = request.cookies.get("zhicai_book")
    if raw in (None, "", ALL_BOOKS):
        return ALL_BOOKS
    try:
        return int(raw)
    except ValueError:
        return ALL_BOOKS


def cross_book_allowed(table: str) -> bool:
    """总览模式下允许跨账套查询的模型白名单。"""
    return table in CROSS_BOOK_ALLOWED


def parse_book_id(raw: str | None) -> int | str:
    if raw in (None, "", ALL_BOOKS):
        return ALL_BOOKS
    try:
        return int(raw)
    except ValueError:
        return ALL_BOOKS
