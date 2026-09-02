# -*- coding: utf-8 -*-
"""res_partner 模块服务：新建客户（账套）向导的核心事务（项目书 7.3）。

事务边界：res_book + 科目克隆 + 默认账簿 + 编号器 一次成型，失败整体回滚。
"""
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.audit import log_action
from ...core.errors import BizError
from ..account.service import init_book_accounting
from .models import ResBook, ResPartner


def _next_book_code(db: Session) -> str:
    """自动生成账套编号：C001、C002…（按现有最大编号递增）。"""
    max_code = db.execute(
        select(func.max(ResBook.code)).where(ResBook.code.like("C%"))
    ).scalar_one_or_none()
    if not max_code:
        return "C001"
    try:
        return f"C{int(max_code[1:]) + 1:03d}"
    except ValueError:
        return "C001"


def create_book(db: Session, payload: dict, user_id: int | None) -> ResBook:
    """新建客户账套：基本信息 + 科目表初始化 + 账簿 + 编号器。

    payload: {name, short_name, credit_no?, taxpayer_type, accounting_standard,
              vat_period?, is_foreign_trade?, industry?, legal_person?, phone?,
              address?, bookkeeping_start?, remark?, code?}
    """
    name = (payload.get("name") or "").strip()
    short_name = (payload.get("short_name") or "").strip()
    if not name:
        raise BizError("name_required", "客户公司全称必填")
    if not short_name:
        short_name = name[:20]

    credit_no = (payload.get("credit_no") or "").strip() or None
    if credit_no:
        dup = db.execute(
            select(ResBook.id).where(ResBook.credit_no == credit_no, ResBook.active.is_(True))
        ).scalar_one_or_none()
        if dup is not None:
            raise BizError("credit_no_dup", f"统一社会信用代码已存在（账套 #{dup}），请核对是否重复建档")

    code = (payload.get("code") or "").strip() or _next_book_code(db)
    dup_code = db.execute(select(ResBook.id).where(ResBook.code == code)).scalar_one_or_none()
    if dup_code is not None:
        raise BizError("code_dup", f"账套编号已存在：{code}")

    taxpayer_type = payload.get("taxpayer_type") or "small"
    accounting_standard = payload.get("accounting_standard") or "small"
    vat_period = payload.get("vat_period") or ("monthly" if taxpayer_type == "general" else "quarterly")

    bookkeeping_start = payload.get("bookkeeping_start")
    if isinstance(bookkeeping_start, str) and bookkeeping_start:
        bookkeeping_start = date.fromisoformat(bookkeeping_start[:10])

    book = ResBook(
        code=code, name=name, short_name=short_name, credit_no=credit_no,
        taxpayer_type=taxpayer_type,
        is_foreign_trade=bool(payload.get("is_foreign_trade", False)),
        industry=payload.get("industry"), legal_person=payload.get("legal_person"),
        phone=payload.get("phone"), address=payload.get("address"),
        accounting_standard=accounting_standard, vat_period=vat_period,
        bookkeeping_start=bookkeeping_start,
        charge_status="normal", remark=payload.get("remark"),
        create_uid=user_id, create_date=datetime.now(), write_uid=user_id, write_date=datetime.now(),
    )
    db.add(book)
    db.flush()  # 拿 book.id

    # 科目表 + 账簿 + 编号器（同一事务）
    result = init_book_accounting(db, book.id, accounting_standard)

    # M3：为新账套克隆内置自动记账规则。
    # 延迟导入避免模块循环依赖：auto_entry 依赖 res_partner，
    # 因此 res_partner 不能在模块顶层 import auto_entry。
    from ..auto_entry.seed_rules import seed_rules_for_book
    rule_count = seed_rules_for_book(db, book.id)

    log_action(db, "res_book", book.id, user_id, "init",
               f"账套初始化完成：{result['accounts']} 个科目、{result['journals']} 个账簿、"
               f"{rule_count} 条自动记账规则")
    db.flush()
    return book


def update_book(db: Session, book: ResBook, updates: dict, user_id: int | None):
    """更新账套基本信息（服务状态与基础字段）。"""
    allowed = {"name", "short_name", "credit_no", "taxpayer_type", "is_foreign_trade", "industry",
               "legal_person", "phone", "address", "vat_period", "bookkeeping_start",
               "bank_accounts", "charge_status", "remark"}
    for k, v in (updates or {}).items():
        if k in allowed:
            setattr(book, k, v)
    book.write_uid = user_id
    book.write_date = datetime.now()
    db.flush()
