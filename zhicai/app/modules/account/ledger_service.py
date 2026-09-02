# -*- coding: utf-8 -*-
"""账簿服务：期末结转 / 总账 / 明细账 / 科目余额表（项目书 7.5）。

核心口径：
- 只有 state=posted 的凭证计入账务（draft 是草稿，不进账）；
- 余额按科目方向计算：借方方向 期末=期初+借-贷；贷方方向 期末=期初+贷-借；
- 科目层级用「编码 + 点号」父子关系（如 6601 → 6601.01）。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ...core.sequence import ensure_sequence, next_number
from .models import AccountAccount, AccountJournal, AccountMove, AccountMoveLine
from .move_service import (
    PL_ACCOUNT_CODES,
    PROFIT_ACCOUNT_CODE,
    _dec,
    assert_period_open,
    lines_of,
    period_of,
)

ZERO = Decimal("0.00")


# ==================== 基础取数 ====================

def _line_sums(db: Session, book_id: int, account_ids: list[int] | None = None,
               period_from: str | None = None, period_to: str | None = None,
               exclude_period: str | None = None,
               exclude_closing: bool = False) -> tuple[Decimal, Decimal]:
    """统计已过账分录的借贷发生额合计。

    period_from/to 为 None 表示不限；exclude_period 可排除某期间（红冲场景）。
    exclude_closing=True 时排除期末结转凭证——利润表取经营成果发生额时必须用：
    结转凭证会把损益科目冲平，若不排除，结转后收入/费用净额都变 0，利润表全空。

    注意：逐科目循环调本函数是 N+1 查询（100 账套 10 年数据下科目余额表
    会超 300ms 预算）——批量场景请用 _sums_by_account 一次 GROUP BY 取回。
    """
    q = (
        select(func.coalesce(func.sum(AccountMoveLine.debit), 0),
               func.coalesce(func.sum(AccountMoveLine.credit), 0))
        .join(AccountMove, AccountMove.id == AccountMoveLine.move_id)
        .where(AccountMoveLine.book_id == book_id,
               AccountMoveLine.active.is_(True),
               AccountMove.state == "posted",
               AccountMove.active.is_(True))
    )
    if account_ids is not None:
        if not account_ids:
            return ZERO, ZERO
        q = q.where(AccountMoveLine.account_id.in_(account_ids))
    if period_from:
        q = q.where(AccountMove.period >= period_from)
    if period_to:
        q = q.where(AccountMove.period <= period_to)
    if exclude_period:
        q = q.where(AccountMove.period != exclude_period)
    if exclude_closing:
        q = q.where(AccountMove.source_type != "closing")
    d, c = db.execute(q).one()
    return _dec(d), _dec(c)


def _sums_by_account(db: Session, book_id: int, period_from: str | None = None,
                     period_to: str | None = None,
                     exclude_closing: bool = False) -> dict[int, tuple[Decimal, Decimal]]:
    """一次 GROUP BY 取回「科目 → (借合计, 贷合计)」——科目余额表/总账的批量取数。"""
    q = (
        select(AccountMoveLine.account_id,
               func.coalesce(func.sum(AccountMoveLine.debit), 0),
               func.coalesce(func.sum(AccountMoveLine.credit), 0))
        .join(AccountMove, AccountMove.id == AccountMoveLine.move_id)
        .where(AccountMoveLine.book_id == book_id,
               AccountMoveLine.active.is_(True),
               AccountMoveLine.account_id.isnot(None),
               AccountMove.state == "posted",
               AccountMove.active.is_(True))
    )
    if period_from:
        q = q.where(AccountMove.period >= period_from)
    if period_to:
        q = q.where(AccountMove.period <= period_to)
    if exclude_closing:
        q = q.where(AccountMove.source_type != "closing")
    q = q.group_by(AccountMoveLine.account_id)
    return {aid: (_dec(d), _dec(c)) for aid, d, c in db.execute(q).all()}


def _agg_sums(sums: dict[int, tuple[Decimal, Decimal]],
              ids: list[int]) -> tuple[Decimal, Decimal]:
    """把若干科目的合计在内存里加总（配合 _sums_by_account 用）。"""
    d = c = ZERO
    for i in ids:
        s = sums.get(i)
        if s:
            d += s[0]
            c += s[1]
    return d, c


def _tree_index(accounts: list[AccountAccount]) -> dict[int, list[int]]:
    """id → 自身 + 全部下级科目 id（编码前缀父子关系，内存计算免逐科目查库）。"""
    return {
        a.id: [x.id for x in accounts
               if x.code == a.code or x.code.startswith(a.code + ".")]
        for a in accounts
    }


def _leaf_and_descendants(db: Session, book_id: int, acc: AccountAccount) -> list[int]:
    """取科目自身 + 全部下级科目 id（用于父科目余额汇总）。"""
    rows = db.execute(
        select(AccountAccount.id, AccountAccount.code)
        .where(AccountAccount.book_id == book_id, AccountAccount.active.is_(True))
    ).all()
    prefix = acc.code + "."
    return [r[0] for r in rows if r[1] == acc.code or r[1].startswith(prefix)]


def signed_balance(db: Session, book_id: int, acc: AccountAccount, period_to: str | None = None,
                   period_from: str | None = None) -> Decimal:
    """有符号余额：借方方向为正，贷方方向为负。"""
    ids = _leaf_and_descendants(db, book_id, acc)
    d, c = _line_sums(db, book_id, ids, period_from=period_from, period_to=period_to)
    if acc.direction == "credit":
        return c - d
    return d - c


def opening_balance(db: Session, book_id: int, acc: AccountAccount, period_from: str) -> Decimal:
    """期初余额（period < period_from 的累计），有符号。"""
    ids = _leaf_and_descendants(db, book_id, acc)
    d, c = _line_sums(db, book_id, ids, period_to=_prev_period(period_from))
    if acc.direction == "credit":
        return c - d
    return d - c


def _split_balance(ending: Decimal, direction: str) -> tuple[Decimal, Decimal]:
    """把「按科目方向的有符号余额」拆成会计实务的借方余额 / 贷方余额两列。

    - direction=debit（资产/成本费用）：正常余额在借方，ending>0 → 借方余额
    - direction=credit（负债/权益/收入）：正常余额在贷方，ending>0 → 贷方余额
    科目余额表的校验口径：借方余额合计 == 贷方余额合计。
    """
    if direction == "debit":
        return (ending, ZERO) if ending >= 0 else (ZERO, -ending)
    return (ZERO, ending) if ending >= 0 else (-ending, ZERO)


def _prev_period(period: str) -> str:
    """YYYY-MM → 上一期（用于期初取数：严格小于 period_from）。"""
    y, m = int(period[:4]), int(period[5:7])
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y:04d}-{m:02d}"


def all_accounts(db: Session, book_id: int) -> list[AccountAccount]:
    return db.execute(
        select(AccountAccount)
        .where(AccountAccount.book_id == book_id, AccountAccount.active.is_(True))
        .order_by(AccountAccount.code)
    ).scalars().all()


def _period_range(year: int, month_from: int, month_to: int) -> tuple[str, str]:
    return f"{year:04d}-{month_from:02d}", f"{year:04d}-{month_to:02d}"


# ==================== 期末结转（项目书 7.5） ====================

def carry_forward(db: Session, book_id: int, period: str, user_id: int | None = None,
                  summary: str | None = None) -> AccountMove:
    """一键结转损益到本年利润（3103）。

    - 取全部损益类**末级**科目（代码前缀命中 PL_ACCOUNT_CODES）的期末余额；
    - 借方余额 → 贷方冲平；贷方余额 → 借方冲平；
    - 差额进 3103 本年利润（盈利记贷方、亏损记借方）；
    - 同期间重复执行直接报错。
    """
    assert_period_open(db, book_id, period, "结转")

    existed = db.execute(
        select(AccountMove.id).where(AccountMove.book_id == book_id,
                                     AccountMove.period == period,
                                     AccountMove.source_type == "closing",
                                     AccountMove.active.is_(True))
    ).scalar_one_or_none()
    if existed is not None:
        raise BizError("already_closed_period", f"期间 {period} 已生成过结转凭证，不能重复结转")

    accounts = all_accounts(db, book_id)
    pl_accounts = [
        a for a in accounts
        if a.is_leaf and a.code.startswith(PL_ACCOUNT_CODES)
    ]
    if not pl_accounts:
        raise BizError("no_pl_account", "科目表中没有损益类科目，无法结转")

    profit_acc = next((a for a in accounts if a.code == PROFIT_ACCOUNT_CODE), None)
    if profit_acc is None:
        raise BizError("no_profit_account", f"科目表缺少「{PROFIT_ACCOUNT_CODE} 本年利润」，无法结转")

    lines: list[dict] = []
    for acc in pl_accounts:
        # 注意 signed_balance 的语义是「正常方向为正」：
        #   费用类(direction=debit) 余额 500 → bal=+500 表示借方余额
        #   收入类(direction=credit) 余额 10000 → bal=+10000 表示**贷方**余额
        # 因此必须结合 direction 判断，不能简单用 bal>0 当借方余额，
        # 否则收入科目会被反向再贷一次（余额翻倍）。
        bal = signed_balance(db, book_id, acc, period_to=period)
        if bal == 0:
            continue
        if acc.direction == "debit":      # 借方余额（费用/成本）→ 贷方冲平
            lines.append({"account_id": acc.id, "debit": ZERO, "credit": bal,
                          "summary": f"结转{acc.name}"})
        else:                             # 贷方余额（收入）→ 借方冲平
            lines.append({"account_id": acc.id, "debit": bal, "credit": ZERO,
                          "summary": f"结转{acc.name}"})

    if not lines:
        raise BizError("nothing_to_carry", f"期间 {period} 损益类科目余额均为 0，无需结转")

    total_debit = sum((_dec(l["debit"]) for l in lines), ZERO)
    total_credit = sum((_dec(l["credit"]) for l in lines), ZERO)
    diff = total_debit - total_credit   # >0 盈利，<0 亏损

    if diff > 0:
        lines.append({"account_id": profit_acc.id, "debit": ZERO, "credit": diff,
                      "summary": summary or f"{period} 结转本年利润"})
    elif diff < 0:
        lines.append({"account_id": profit_acc.id, "debit": -diff, "credit": ZERO,
                      "summary": summary or f"{period} 结转本年利润"})

    # 结转凭证日期取该期间最后一天
    y, m = int(period[:4]), int(period[5:7])
    last_day = _last_day_of_month(y, m)

    from .move_service import create_move, post_move  # 局部导入避免循环
    move = create_move(db, book_id=book_id, journal_id=_default_journal_id(db, book_id),
                       move_date=last_day, lines=[
                           {"summary": l["summary"], "account_id": l["account_id"],
                            "debit": str(l["debit"]), "credit": str(l["credit"])}
                           for l in lines
                       ],
                       source_type="closing", user_id=user_id,
                       remark=f"期末损益结转（{period}）")
    return post_move(db, move.id, user_id)


def _last_day_of_month(y: int, m: int) -> date:
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - __import__("datetime").timedelta(days=1)


def _default_journal_id(db: Session, book_id: int) -> int:
    """取「记」字账簿；没有则取第一个。"""
    j = db.execute(
        select(AccountJournal).where(AccountJournal.book_id == book_id,
                                     AccountJournal.active.is_(True)).order_by(AccountJournal.id)
    ).scalars().first()
    if j is None:
        raise BizError("no_journal", "该账套没有凭证字（账簿），请先初始化账套")
    return j.id


# ==================== 总账 ====================

def general_ledger(db: Session, book_id: int, period_from: str, period_to: str,
                   account_code: str | None = None) -> list[dict]:
    """总账：科目 × 期间区间 的期初/本期借贷/期末。

    性能：两条 GROUP BY 聚合（期初/本期）+ 内存汇总，替代逐科目 2 次查询的 N+1。
    """
    accounts = all_accounts(db, book_id)
    if account_code:
        accounts = [a for a in accounts if a.code.startswith(account_code)]
    tree = _tree_index(accounts)
    open_sums = _sums_by_account(db, book_id, period_to=_prev_period(period_from))
    cur_sums = _sums_by_account(db, book_id, period_from=period_from, period_to=period_to)

    rows = []
    for acc in accounts:
        ids = tree[acc.id]
        open_d, open_c = _agg_sums(open_sums, ids)
        cur_d, cur_c = _agg_sums(cur_sums, ids)
        if acc.direction == "credit":
            opening, ending = open_c - open_d, (open_c - open_d) + (cur_c - cur_d)
        else:
            opening, ending = open_d - open_c, (open_d - open_c) + (cur_d - cur_c)
        if opening == 0 and cur_d == 0 and cur_c == 0 and ending == 0:
            continue  # 无发生额不展示
        dbal, cbal = _split_balance(ending, acc.direction)
        rows.append({
            "account_id": acc.id, "code": acc.code, "name": acc.name,
            "direction": acc.direction, "is_leaf": acc.is_leaf,
            "opening": str(opening), "debit": str(cur_d), "credit": str(cur_c),
            "ending": str(ending),
            "debit_balance": str(dbal), "credit_balance": str(cbal),
        })
    return rows


# ==================== 明细账 ====================

def subsidiary_ledger(db: Session, book_id: int, account_id: int,
                      period_from: str, period_to: str) -> dict:
    """明细账：科目下按凭证逐笔展开（日期/凭证号/摘要/借/贷/方向余额）。"""
    acc = db.get(AccountAccount, account_id)
    if acc is None:
        raise BizError("account_not_found", "科目不存在")

    q = (
        select(AccountMoveLine, AccountMove)
        .join(AccountMove, AccountMove.id == AccountMoveLine.move_id)
        .where(AccountMoveLine.book_id == book_id,
               AccountMoveLine.account_id == account_id,
               AccountMoveLine.active.is_(True),
               AccountMove.state == "posted",
               AccountMove.active.is_(True),
               AccountMove.period >= period_from,
               AccountMove.period <= period_to)
        .order_by(AccountMove.move_date, AccountMove.id, AccountMoveLine.line_no)
    )
    pairs = db.execute(q).all()

    # 期初余额
    open_d, open_c = _line_sums(db, book_id, [account_id], period_to=_prev_period(period_from))
    running = (open_d - open_c) if acc.direction == "debit" else (open_c - open_d)

    items = []
    for ln, mv in pairs:
        d, c = _dec(ln.debit), _dec(ln.credit)
        running = running + d - c if acc.direction == "debit" else running + c - d
        items.append({
            "line_id": ln.id, "move_id": mv.id, "move_name": mv.name,
            "move_date": mv.move_date.isoformat(), "period": mv.period,
            "summary": ln.summary, "debit": str(d), "credit": str(c),
            "balance": str(running),
            "balance_direction": "借" if running >= 0 else "贷",
        })

    return {
        "account": {"id": acc.id, "code": acc.code, "name": acc.name, "direction": acc.direction},
        "period_from": period_from, "period_to": period_to,
        "opening": str(running - sum((Decimal(i["debit"]) - Decimal(i["credit"])
                                      for i in items), ZERO))
        if acc.direction == "debit" else
        str(running - sum((Decimal(i["credit"]) - Decimal(i["debit"])
                           for i in items), ZERO)),
        "items": items,
        "total_debit": str(sum((Decimal(i["debit"]) for i in items), ZERO)),
        "total_credit": str(sum((Decimal(i["credit"]) for i in items), ZERO)),
        "ending": str(running),
    }


# ==================== 科目余额表 ====================

def trial_balance(db: Session, book_id: int, period_from: str, period_to: str,
                  only_nonzero: bool = True) -> list[dict]:
    """科目余额表：全科目 期初/本期发生/期末（支持期间区间）。

    性能：两条 GROUP BY 聚合（期初/本期）+ 内存汇总上卷父科目，
    替代逐科目 2 次查询的 N+1（M7 压测：10 年数据 380ms → 30ms 级）。
    """
    accounts = all_accounts(db, book_id)
    tree = _tree_index(accounts)
    open_sums = _sums_by_account(db, book_id, period_to=_prev_period(period_from))
    cur_sums = _sums_by_account(db, book_id, period_from=period_from, period_to=period_to)

    rows = []
    for acc in accounts:
        ids = tree[acc.id]
        open_d, open_c = _agg_sums(open_sums, ids)
        cur_d, cur_c = _agg_sums(cur_sums, ids)
        if acc.direction == "credit":
            opening = open_c - open_d
            ending = opening + (cur_c - cur_d)
        else:
            opening = open_d - open_c
            ending = opening + (cur_d - cur_c)
        if only_nonzero and opening == 0 and cur_d == 0 and cur_c == 0 and ending == 0:
            continue
        dbal, cbal = _split_balance(ending, acc.direction)
        rows.append({
            "account_id": acc.id, "code": acc.code, "name": acc.name,
            "account_type": acc.account_type, "direction": acc.direction,
            "is_leaf": acc.is_leaf,
            "opening": str(opening), "debit": str(cur_d), "credit": str(cur_c),
            "ending": str(ending),
            "debit_balance": str(dbal), "credit_balance": str(cbal),
        })
    return rows
