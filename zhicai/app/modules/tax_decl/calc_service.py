# -*- coding: utf-8 -*-
"""申报计算底稿（项目书 7.9）：取数 → 计算 → 输出可追溯快照。

口径：
- 增值税（一般纳税人）= 当期销项税额 − 当期进项税额 − 上期留抵
- 增值税（小规模）= 含税收入 ÷ (1+征收率) × 征收率；季度不超免征额则免征
- 附加税 = 实缴增值税 ×（城建 7% + 教育附加 3% + 地方教育附加 2%）
- 印花税（买卖合同）= 计税依据 × 0.3‰（计税依据默认取当期购销合计，可手改）
- 企业所得税 / 个税：**只出取数汇总**（营业收入/成本/利润总额），
  计算以用户在税局端为准（项目书明确要求）

每条计算都产出 calc_snapshot：取数口径 + 公式 + 明细 + 穿透参数，
让报表上的每个数字都能点回发票/凭证列表核对。
"""
import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ..account.ledger_service import _line_sums
from ..account.models import AccountAccount
from ..base.models import IrConfig
from ..invoice.models import InvoiceBill
from ..res_partner.models import ResBook
from .models import TaxDeclItem

ZERO = Decimal("0.00")
TWO = Decimal("0.01")


def _d(v) -> Decimal:
    if v is None or v == "":
        return ZERO
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q(v: Decimal) -> Decimal:
    return v.quantize(TWO, rounding=ROUND_HALF_UP)


# ==================== 政策参数（存 ir_config，用户可维护） ====================

POLICY_DEFAULTS = {
    "tax.policy.vat_small_rate": "0.03",                # 小规模征收率
    "tax.policy.vat_small_quarter_exempt": "300000",    # 季度免征额（不含税销售额）
    "tax.policy.surtax_city_rate": "0.07",              # 城建税（市区）
    "tax.policy.surtax_edu_rate": "0.03",               # 教育费附加
    "tax.policy.surtax_local_edu_rate": "0.02",         # 地方教育附加
    "tax.policy.stamp_rate": "0.0003",                  # 印花税（买卖合同 0.3‰）
}


def policy(db: Session, key: str) -> Decimal:
    row = db.execute(select(IrConfig).where(IrConfig.key == key)).scalar_one_or_none()
    raw = (row.value if row and row.value else None) or POLICY_DEFAULTS.get(key, "0")
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal(str(POLICY_DEFAULTS.get(key, "0")))


def ensure_policy_config(db: Session) -> None:
    """把默认政策参数写入 ir_config（幂等，已存在不动）。"""
    existed = {
        r[0] for r in db.execute(select(IrConfig.key)).all()
    }
    for k, v in POLICY_DEFAULTS.items():
        if k not in existed:
            db.add(IrConfig(key=k, value=v))
    db.flush()


# ==================== 取数 ====================

def invoice_tax_sum(db: Session, book_id: int, direction: str, period: str,
                    field: str = "tax_amount") -> tuple[Decimal, int]:
    """某期间某方向发票的税额/金额合计 → (合计, 张数)。"""
    q = select(InvoiceBill).where(
        InvoiceBill.book_id == book_id, InvoiceBill.active.is_(True),
        InvoiceBill.direction == direction, InvoiceBill.period == period,
        InvoiceBill.state != "voided")
    rows = db.execute(q).scalars().all()
    total = sum((_d(getattr(r, field)) for r in rows), ZERO)
    return _q(total), len(rows)


def quarter_periods_of(period: str) -> list[str]:
    """季度属期 → 该季度的 3 个月度属期（"2026Q3" → ["2026-07","2026-08","2026-09"]）。"""
    if "Q" not in period.upper():
        return [period]
    y = int(period[:4])
    q = int(period.upper().split("Q")[1])
    start = (q - 1) * 3 + 1
    return [f"{y}-{start + i:02d}" for i in range(3)]


def account_period_amount(db: Session, book_id: int, code_prefixes: list[str],
                          period_from: str, period_to: str) -> Decimal:
    """按科目代码前缀取期间发生额（按科目方向折算：收入类取贷-借，费用类取借-贷）。"""
    from ..account.ledger_service import all_accounts
    accounts = all_accounts(db, book_id)
    matched = [a for a in accounts if a.is_leaf and any(
        a.code == c or a.code.startswith(c + ".") for c in code_prefixes)]
    total = ZERO
    for a in matched:
        d, c = _line_sums(db, book_id, [a.id], period_from=period_from, period_to=period_to,
                          exclude_closing=True)
        total += (d - c) if a.direction == "debit" else (c - d)
    return _q(total)


def prev_vat_credit(db: Session, book_id: int, period: str) -> Decimal:
    """上期留抵：取上期增值税台账的 computed_amount，若为负（留抵）则取其绝对值。"""
    rows = db.execute(
        select(TaxDeclItem).where(
            TaxDeclItem.book_id == book_id, TaxDeclItem.tax_kind == "vat",
            TaxDeclItem.active.is_(True), TaxDeclItem.period < period)
        .order_by(TaxDeclItem.period.desc()).limit(1)
    ).scalars().all()
    if not rows:
        return ZERO
    amt = _d(rows[0].computed_amount)
    return -amt if amt < 0 else ZERO


def prev_vat_paid(db: Session, book_id: int, period: str) -> Decimal:
    """上期（或本期对应属期）实缴增值税——附加税的计税依据。"""
    row = db.execute(
        select(TaxDeclItem).where(
            TaxDeclItem.book_id == book_id, TaxDeclItem.tax_kind == "vat",
            TaxDeclItem.active.is_(True), TaxDeclItem.period == period)
    ).scalars().first()
    if not row:
        return ZERO
    return _d(row.declared_amount if row.declared_amount is not None else row.computed_amount)


# ==================== 计算入口 ====================

def compute(db: Session, item: TaxDeclItem, overrides: dict | None = None) -> dict:
    """计算某个台账行的应纳税额，返回 calc_snapshot（并写回 item）。

    overrides 可手工改取数（如印花税计税依据）。
    """
    book = db.get(ResBook, item.book_id)
    if book is None:
        raise BizError("book_not_found", "账套不存在")
    ov = overrides or {}

    if item.tax_kind == "vat":
        snap = _calc_vat(db, book, item, ov)
    elif item.tax_kind == "surtax":
        snap = _calc_surtax(db, book, item, ov)
    elif item.tax_kind == "stamp":
        snap = _calc_stamp(db, book, item, ov)
    elif item.tax_kind in ("cit_quarterly", "cit_annual"):
        snap = _calc_cit(db, book, item, ov)
    elif item.tax_kind == "iit":
        snap = _calc_iit(db, book, item, ov)
    else:
        raise BizError("tax_kind_unsupported", f"暂不支持计算税种：{item.tax_kind}")

    item.computed_amount = snap["result"]
    item.calc_snapshot = json.dumps(snap, ensure_ascii=False)
    item.write_date = datetime.now()
    if item.state == "pending":
        item.state = "preparing"
    db.flush()
    return snap


def _base_snap(item, formula: str, note: str = "") -> dict:
    return {
        "tax_kind": item.tax_kind, "period": item.period, "book_id": item.book_id,
        "formula": formula, "note": note,
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": [], "result": "0.00",
    }


def _src_invoice(direction: str, period: str, count: int) -> dict:
    """发票取数的穿透参数（前端可跳转发票列表并带筛选）。"""
    return {"type": "invoice", "direction": direction, "period": period,
            "count": count, "route": f"/invoices?direction={direction}&period={period}"}


# ---------- 增值税 ----------

def _calc_vat(db: Session, book: ResBook, item: TaxDeclItem, ov: dict) -> dict:
    is_small = getattr(book, "taxpayer_type", "small") == "small"
    periods = quarter_periods_of(item.period) if "Q" in item.period.upper() else [item.period]

    if is_small:
        rate = _d(ov.get("rate") or policy(db, "tax.policy.vat_small_rate"))
        exempt_limit = _d(ov.get("exempt_limit") or
                          policy(db, "tax.policy.vat_small_quarter_exempt"))
        # 小规模按季申报：汇总整个季度的含税销售额
        total_incl = ZERO
        out_cnt = 0
        detail = []
        for p in periods:
            amt, cnt = invoice_tax_sum(db, book.id, "output", p, "total_amount")
            total_incl += amt
            out_cnt += cnt
            detail.append({"label": f"{p} 含税销售额", "amount": str(_q(amt)),
                           "count": cnt, "source": _src_invoice("output", p, cnt)})
        excl = _q(total_incl / (Decimal("1") + rate)) if rate != Decimal("-1") else ZERO
        taxable = _q(excl * rate)
        exempted = excl <= exempt_limit
        result = ZERO if exempted else taxable

        snap = _base_snap(item, f"小规模：应纳税额 = 含税销售额 ÷ (1+{rate}) × {rate}")
        snap["policy"] = {"mode": "small", "rate": str(rate),
                          "quarter_exempt_limit": str(exempt_limit)}
        snap["items"] = detail + [
            {"label": "不含税销售额", "amount": str(excl), "source": None},
            {"label": "季度免征额", "amount": str(_q(exempt_limit)), "source": None},
            {"label": "是否免征", "amount": "是" if exempted else "否", "source": None},
        ]
        snap["result"] = str(result)
        snap["note"] = ("季度不含税销售额未超过免征额，本期免征增值税"
                        if exempted else "")
        return snap

    # 一般纳税人
    out_tax = ZERO
    in_tax = ZERO
    detail = []
    out_cnt_total = in_cnt_total = 0
    for p in periods:
        amt, cnt = invoice_tax_sum(db, book.id, "output", p, "tax_amount")
        out_tax += amt
        out_cnt_total += cnt
        detail.append({"label": f"{p} 销项税额", "amount": str(_q(amt)),
                       "source": _src_invoice("output", p, cnt)})
        amt2, cnt2 = invoice_tax_sum(db, book.id, "input", p, "tax_amount")
        in_tax += amt2
        in_cnt_total += cnt2
        detail.append({"label": f"{p} 进项税额", "amount": str(_q(amt2)),
                       "source": _src_invoice("input", p, cnt2)})
    credit = prev_vat_credit(db, book.id, item.period)
    result = _q(out_tax - in_tax - credit)

    snap = _base_snap(item, "一般纳税人：应纳税额 = 销项税额 − 进项税额 − 上期留抵")
    snap["policy"] = {"mode": "general"}
    snap["items"] = detail + [
        {"label": "销项税额合计", "amount": str(_q(out_tax)), "count": out_cnt_total,
         "source": _src_invoice("output", item.period, out_cnt_total)},
        {"label": "进项税额合计", "amount": str(_q(in_tax)), "count": in_cnt_total,
         "source": _src_invoice("input", item.period, in_cnt_total)},
        {"label": "上期留抵", "amount": str(_q(credit)), "source": None},
    ]
    snap["result"] = str(result)
    if result < 0:
        snap["note"] = "本期进项大于销项，形成留抵（应纳税额为 0，负数表示留抵金额）"
    return snap


# ---------- 附加税 ----------

def _calc_surtax(db: Session, book: ResBook, item: TaxDeclItem, ov: dict) -> dict:
    base = _d(ov.get("base")) if ov.get("base") is not None else prev_vat_paid(
        db, book.id, item.period)
    city_rate = _d(ov.get("city_rate") or policy(db, "tax.policy.surtax_city_rate"))
    edu_rate = _d(ov.get("edu_rate") or policy(db, "tax.policy.surtax_edu_rate"))
    local_rate = _d(ov.get("local_rate") or
                    policy(db, "tax.policy.surtax_local_edu_rate"))

    city = _q(base * city_rate)
    edu = _q(base * edu_rate)
    local = _q(base * local_rate)
    result = _q(city + edu + local)

    snap = _base_snap(
        item,
        f"附加税 = 实缴增值税 ×（城建 {city_rate} + 教育附加 {edu_rate} "
        f"+ 地方教育附加 {local_rate}）")
    snap["policy"] = {"city_rate": str(city_rate), "edu_rate": str(edu_rate),
                      "local_edu_rate": str(local_rate)}
    snap["items"] = [
        {"label": "计税依据（实缴增值税）", "amount": str(_q(base)), "source": None},
        {"label": "城建税", "amount": str(city), "source": None},
        {"label": "教育费附加", "amount": str(edu), "source": None},
        {"label": "地方教育附加", "amount": str(local), "source": None},
    ]
    snap["result"] = str(result)
    if base == 0:
        snap["note"] = "未取到实缴增值税（需先完成增值税申报并填写实缴额），附加税暂按 0 计算"
    return snap


# ---------- 印花税 ----------

def _calc_stamp(db: Session, book: ResBook, item: TaxDeclItem, ov: dict) -> dict:
    rate = _d(ov.get("rate") or policy(db, "tax.policy.stamp_rate"))
    periods = quarter_periods_of(item.period) if "Q" in item.period.upper() else [item.period]

    buy = sell = ZERO
    detail = []
    for p in periods:
        s_amt, s_cnt = invoice_tax_sum(db, book.id, "output", p, "total_amount")
        b_amt, b_cnt = invoice_tax_sum(db, book.id, "input", p, "total_amount")
        sell += s_amt
        buy += b_amt
        detail.append({"label": f"{p} 销售额", "amount": str(_q(s_amt)),
                       "source": _src_invoice("output", p, s_cnt)})
        detail.append({"label": f"{p} 采购额", "amount": str(_q(b_amt)),
                       "source": _src_invoice("input", p, b_cnt)})
    default_base = _q(buy + sell)
    base = _d(ov["base"]) if ov.get("base") is not None else default_base
    result = _q(base * rate)

    snap = _base_snap(item, f"印花税（买卖合同）= 计税依据 × {rate}（0.3‰）")
    snap["policy"] = {"rate": str(rate)}
    snap["items"] = detail + [
        {"label": "计税依据（购销合计，可手工调整）", "amount": str(base),
         "source": None, "editable": True},
    ]
    snap["result"] = str(result)
    return snap


# ---------- 企业所得税 / 个税（仅取数汇总） ----------

def _calc_cit(db: Session, book: ResBook, item: TaxDeclItem, ov: dict) -> dict:
    periods = quarter_periods_of(item.period) if "Q" in item.period.upper() else None
    if periods:
        p_from, p_to = periods[0], periods[-1]
    elif len(item.period) == 4:
        p_from, p_to = f"{item.period}-01", f"{item.period}-12"
    else:
        p_from = p_to = item.period

    revenue = account_period_amount(db, book.id, ["6001", "6051"], p_from, p_to)
    cost = account_period_amount(db, book.id, ["6401", "6402"], p_from, p_to)
    expense = account_period_amount(db, book.id, ["6601", "6602", "6603", "6403"],
                                    p_from, p_to)
    profit = _q(revenue - cost - expense)

    snap = _base_snap(
        item, "企业所得税：系统仅提供取数汇总，具体计算以用户在电子税务局申报为准")
    snap["policy"] = {"mode": "summary_only"}
    snap["items"] = [
        {"label": "营业收入", "amount": str(revenue), "source": {"type": "account",
                                                                 "accounts": ["6001", "6051"]}},
        {"label": "营业成本", "amount": str(cost), "source": {"type": "account",
                                                              "accounts": ["6401", "6402"]}},
        {"label": "期间费用", "amount": str(expense),
         "source": {"type": "account", "accounts": ["6601", "6602", "6603", "6403"]}},
        {"label": "利润总额（收入−成本−费用）", "amount": str(profit), "source": None},
    ]
    snap["result"] = "0.00"
    snap["note"] = "本系统不做所得税计算，请以上述取数在税局端申报后回填实缴额"
    return snap


def _calc_iit(db: Session, book: ResBook, item: TaxDeclItem, ov: dict) -> dict:
    p_from = p_to = item.period
    salary = account_period_amount(db, book.id, ["2211.01"], p_from, p_to)

    snap = _base_snap(item, "个人所得税：系统仅提供取数汇总，明细以自然人电子税务局为准")
    snap["policy"] = {"mode": "summary_only"}
    snap["items"] = [
        {"label": "应付职工薪酬（工资）", "amount": str(salary),
         "source": {"type": "account", "accounts": ["2211.01"]}},
    ]
    snap["result"] = "0.00"
    snap["note"] = "个税计算以自然人电子税务局为准，本系统仅登记申报状态"
    return snap
