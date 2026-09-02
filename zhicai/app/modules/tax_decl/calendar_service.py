# -*- coding: utf-8 -*-
"""征期服务：截止日计算 + 台账批量生成（幂等）（项目书 6.10 / 7.9 DoD）。

属期 period 三种格式：
  - 月度："2026-09"
  - 季度："2026Q3"
  - 年度："2026"

性能：DoD 要求覆盖 100 账套的台账生成 < 10 秒。
做法是一次性把"已存在台账的 (book, tax_kind, period)"读进内存做去重，
再用批量 add + 单次 flush，避免逐条查询（N+1）。
"""
import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ..res_partner.models import ResBook
from .models import TaxCalendarRule, TaxDeclItem


# ==================== 属期与截止日 ====================

def _next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def deadline_of(period: str, deadline_rule: str) -> date:
    """按规则算申报截止日。

    - next_month_15         ：属期次月 15 日（月度申报）
    - quarter_next_month_15 ：属期所在季度的次季首月 15 日（季度申报）
    - annual_0531           ：属期次年度 5 月 31 日（年度汇算）
    """
    p = (period or "").strip()
    if deadline_rule == "next_month_15":
        if len(p) != 7 or p[4] != "-":
            raise BizError("period_format", f"月度属期格式应为 YYYY-MM，实际 {period}")
        y, m = int(p[:4]), int(p[5:7])
        ny, nm = _next_month(y, m)
        return date(ny, nm, 15)

    if deadline_rule == "quarter_next_month_15":
        if "Q" not in p.upper():
            raise BizError("period_format", f"季度属期格式应为 YYYYQn，实际 {period}")
        y = int(p[:4])
        q = int(p.upper().split("Q")[1])
        if q not in (1, 2, 3, 4):
            raise BizError("period_format", f"季度必须是 1-4，实际 {period}")
        end_month = q * 3                     # Q3 → 9 月
        ny, nm = _next_month(y, end_month)    # 次季首月
        return date(ny, nm, 15)

    if deadline_rule == "annual_0531":
        return date(int(p[:4]) + 1, 5, 31)

    raise BizError("deadline_rule_unknown", f"未知的截止日规则：{deadline_rule}")


def period_kind_of(period: str) -> str:
    """属期字符串 → monthly / quarterly / yearly。"""
    p = (period or "").strip()
    if "Q" in p.upper():
        return "quarterly"
    if len(p) == 4 and p.isdigit():
        return "yearly"
    return "monthly"


def quarter_period_of(month_period: str) -> str:
    """月度属期 → 所属季度属期（"2026-09" → "2026Q3"）。"""
    y, m = int(month_period[:4]), int(month_period[5:7])
    return f"{y}Q{(m - 1) // 3 + 1}"


def is_quarter_end(month_period: str) -> bool:
    return int(month_period[5:7]) in (3, 6, 9, 12)


def periods_to_generate(month_period: str) -> list[str]:
    """给一个月度属期，展开出本次应生成的全部属期。

    例："2026-09" → ["2026-09"（月度项）, "2026Q3"（季度项，9 月是季末）]
        "2026-08" → ["2026-08"]
    """
    out = [month_period]
    if is_quarter_end(month_period):
        out.append(quarter_period_of(month_period))
    return out


# ==================== 规则适用性 ====================

def rule_applies(rule: TaxCalendarRule, book: ResBook) -> bool:
    """按 applies_to（JSON）判断规则是否适用于该账套。"""
    if not rule.applies_to:
        return True
    try:
        cond = json.loads(rule.applies_to) or {}
    except (ValueError, TypeError):
        return True
    if not isinstance(cond, dict):
        return True
    for key, expect in cond.items():
        actual = getattr(book, key, None)
        vals = expect if isinstance(expect, list) else [expect]
        if actual not in vals:
            return False
    return True


# ==================== 批量生成（幂等） ====================

def generate_items(db: Session, periods: list[str], book_ids: list[int] | None = None,
                   user_id: int | None = None) -> dict:
    """按征期规则批量生成申报台账（幂等：已存在的 (账套,税种,属期) 跳过）。

    返回 {"created": n, "skipped": n, "books": m, "periods": [...]}
    """
    if not periods:
        raise BizError("period_required", "请指定要生成的属期")

    books = db.execute(
        select(ResBook).where(ResBook.active.is_(True),
                              ResBook.charge_status != "terminated")
    ).scalars().all()
    if book_ids:
        wanted = set(book_ids)
        books = [b for b in books if b.id in wanted]
    if not books:
        raise BizError("no_books", "没有可生成的账套")

    rules = db.execute(
        select(TaxCalendarRule).where(TaxCalendarRule.active.is_(True),
                                      TaxCalendarRule.enabled.is_(True))
    ).scalars().all()
    if not rules:
        raise BizError("no_rules", "没有启用的征期规则")

    # 一次性读出已存在的台账键，避免逐条查询（100 账套 × 多期间时这是性能关键）
    existing = {
        (r[0], r[1], r[2])
        for r in db.execute(
            select(TaxDeclItem.book_id, TaxDeclItem.tax_kind, TaxDeclItem.period)
            .where(TaxDeclItem.active.is_(True))
        ).all()
    }

    created = skipped = 0
    now = datetime.now()
    # 月度属期要展开出季度项：传 "2026-09"（季末月）应同时生成
    # 月度税种（2026-09）和季度税种（2026Q3，如印花税/所得税预缴），
    # 否则按季申报的税种会被整体漏掉。
    expanded: list[str] = []
    for period in periods:
        if period_kind_of(period) == "monthly":
            expanded.extend(periods_to_generate(period))
        else:
            expanded.append(period)

    for period in expanded:
        pkind = period_kind_of(period)
        applicable = [r for r in rules if r.period_type == pkind]
        if not applicable:
            continue
        for book in books:
            for rule in applicable:
                if not rule_applies(rule, book):
                    continue
                key = (book.id, rule.tax_kind, period)
                if key in existing:
                    skipped += 1
                    continue
                try:
                    due = deadline_of(period, rule.deadline_rule)
                except BizError:
                    continue
                db.add(TaxDeclItem(
                    book_id=book.id, tax_kind=rule.tax_kind, period=period,
                    due_date=due, state="pending", computed_amount=0,
                    source="auto", rule_id=rule.id,
                    create_uid=user_id, create_date=now,
                    write_uid=user_id, write_date=now, active=True,
                ))
                existing.add(key)     # 防止同批内重复
                created += 1

    if created:
        db.flush()
    return {"created": created, "skipped": skipped, "books": len(books),
            "periods": expanded}
