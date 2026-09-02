# -*- coding: utf-8 -*-
"""财务报表：资产负债表 / 利润表（项目书 7.5 DoD ③④）。

- 取数口径：资产负债表取期末余额；利润表取期间发生额。
- 公式映射默认内置（小企业准则格式），允许用 ir_config 覆盖（key 见 FORMULA_KEYS）。
- 资产负债表内置「资产 = 负债 + 所有者权益」平衡校验，不平则返回 diff 供前端红条警示。
"""
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ..base.models import IrConfig
from .ledger_service import all_accounts, signed_balance, _line_sums, _prev_period
from .models import AccountAccount
from .move_service import _dec

ZERO = Decimal("0.00")

# ============ 默认公式（小企业会计准则格式） ============
# 每项：name 显示名，accounts 科目代码前缀列表，side 取数方向
BS_TEMPLATE = {
    "asset_current": {"label": "流动资产", "items": [
        {"name": "货币资金", "accounts": ["1001", "1002", "1012"]},
        {"name": "短期投资", "accounts": ["1101"]},
        {"name": "应收票据", "accounts": ["1121"]},
        {"name": "应收账款", "accounts": ["1122"]},
        {"name": "预付账款", "accounts": ["1123"]},
        {"name": "应收股利", "accounts": ["1131"]},
        {"name": "应收利息", "accounts": ["1132"]},
        {"name": "其他应收款", "accounts": ["1221"]},
        {"name": "存货", "accounts": ["1401", "1403", "1405", "1471"]},
    ]},
    "asset_noncurrent": {"label": "非流动资产", "items": [
        {"name": "长期债券投资", "accounts": ["1501"]},
        {"name": "固定资产", "accounts": ["1601", "1602", "1604", "1606"]},
        {"name": "无形资产", "accounts": ["1701", "1702"]},
        {"name": "长期待摊费用", "accounts": ["1801"]},
    ]},
    "liability_current": {"label": "流动负债", "items": [
        {"name": "短期借款", "accounts": ["2001"]},
        {"name": "应付票据", "accounts": ["2201"]},
        {"name": "应付账款", "accounts": ["2202"]},
        {"name": "预收账款", "accounts": ["2203"]},
        {"name": "应付职工薪酬", "accounts": ["2211"]},
        {"name": "应交税费", "accounts": ["2221"]},
        {"name": "应付利息", "accounts": ["2231"]},
        {"name": "应付利润", "accounts": ["2232"]},
        {"name": "其他应付款", "accounts": ["2241"]},
    ]},
    "liability_noncurrent": {"label": "非流动负债", "items": [
        {"name": "长期借款", "accounts": ["2501"]},
        {"name": "长期应付款", "accounts": ["2701"]},
    ]},
    "equity": {"label": "所有者权益", "items": [
        {"name": "实收资本", "accounts": ["3001"]},
        {"name": "资本公积", "accounts": ["3002"]},
        {"name": "盈余公积", "accounts": ["3101"]},
        # 未分配利润：年末结转前 = 本年利润(3103) + 未分配利润(3104)
        {"name": "未分配利润", "accounts": ["3103", "3104"]},
    ]},
}

PL_TEMPLATE = [
    {"key": "revenue", "name": "一、营业收入", "type": "sum", "items": [
        {"name": "主营业务收入", "accounts": ["6001"]},
        {"name": "其他业务收入", "accounts": ["6051"]},
    ]},
    {"key": "cost", "name": "减：营业成本、税金及附加、期间费用", "type": "sum", "items": [
        {"name": "主营业务成本", "accounts": ["6401"]},
        {"name": "其他业务成本", "accounts": ["6402"]},
        {"name": "税金及附加", "accounts": ["6403"]},
        {"name": "销售费用", "accounts": ["6601"]},
        {"name": "管理费用", "accounts": ["6602"]},
        {"name": "财务费用", "accounts": ["6603"]},
    ]},
    {"key": "invest", "name": "加：投资收益（亏损以 - 填列）", "type": "sum", "items": [
        {"name": "投资收益", "accounts": ["6111"]},
    ]},
    {"key": "operating_profit", "name": "二、营业利润（亏损以 - 填列）", "type": "formula",
     "expr": "revenue - cost + invest"},
    {"key": "nonop_income", "name": "加：营业外收入", "type": "sum", "items": [
        {"name": "营业外收入", "accounts": ["6301"]},
    ]},
    {"key": "nonop_expense", "name": "减：营业外支出", "type": "sum", "items": [
        {"name": "营业外支出", "accounts": ["6711"]},
    ]},
    {"key": "total_profit", "name": "三、利润总额（亏损以 - 填列）", "type": "formula",
     "expr": "operating_profit + nonop_income - nonop_expense"},
    {"key": "tax", "name": "减：所得税费用", "type": "sum", "items": [
        {"name": "所得税费用", "accounts": ["6801"]},
    ]},
    {"key": "net_profit", "name": "四、净利润（亏损以 - 填列）", "type": "formula",
     "expr": "total_profit - tax"},
]

FORMULA_KEYS = {"bs": "report.formula.balance_sheet", "pl": "report.formula.income_statement"}


def _load_formula(db: Session, kind: str, default):
    """从 ir_config 读用户微调过的公式；读不到或损坏则用内置默认。"""
    try:
        row = db.execute(
            select(IrConfig).where(IrConfig.key == FORMULA_KEYS[kind])
        ).scalar_one_or_none()
        if row and row.value:
            return json.loads(row.value)
    except (ValueError, TypeError, KeyError):
        pass
    return default


def _ids_by_code_prefix(db: Session, book_id: int, codes: list[str]) -> list[int]:
    """按科目代码前缀匹配（含下级明细科目）。"""
    accounts = all_accounts(db, book_id)
    ids = []
    for a in accounts:
        for c in codes:
            if a.code == c or a.code.startswith(c + "."):
                ids.append(a.id)
                break
    return ids


def _balance_sum(db: Session, book_id: int, codes: list[str], period_to: str) -> Decimal:
    """期末余额合计（按各科目方向折算成有符号后相加，用于资产负债表）。

    只遍历**末级科目**：父科目余额本来就由子科目汇总而来，若父科目也参与累加，
    子科目金额会被重复计算（如 6601 与 6601.01 同时命中时金额翻倍）。
    """
    accounts = all_accounts(db, book_id)
    matched = [a for a in accounts
               if a.is_leaf and any(a.code == c or a.code.startswith(c + ".") for c in codes)]
    return sum((signed_balance(db, book_id, a, period_to=period_to) for a in matched), ZERO)


def _period_amount(db: Session, book_id: int, codes: list[str], period_from: str,
                   period_to: str, side: str = "auto") -> Decimal:
    """利润表取数：按期间发生额（**排除期末结转凭证**）。

    必须排除结转：结转凭证把损益科目借贷冲平，若不排除，结转后收入/费用的
    期间净额都变成 0，利润表会整张归零。

    side=auto：按科目方向自动折算（收入类取贷-借，费用类取借-贷）；
    side=debit/credit：强制取单向发生额。
    """
    accounts = all_accounts(db, book_id)
    matched = [a for a in accounts
               if a.is_leaf and any(a.code == c or a.code.startswith(c + ".") for c in codes)]
    ids = [a.id for a in matched]
    if not ids:
        return ZERO
    d, c = _line_sums(db, book_id, ids, period_from=period_from, period_to=period_to,
                      exclude_closing=True)
    if side == "debit":
        return d
    if side == "credit":
        return c
    # auto：按科目方向折算
    total = ZERO
    for a in matched:
        ids_one = [a.id]
        d1, c1 = _line_sums(db, book_id, ids_one, period_from=period_from, period_to=period_to,
                            exclude_closing=True)
        total += (d1 - c1) if a.direction == "debit" else (c1 - d1)
    return total


# ==================== 资产负债表 ====================

def balance_sheet(db: Session, book_id: int, period_to: str,
                  period_from: str | None = None) -> dict:
    """资产负债表（期末时点报表）。

    DoD ③：内置 资产 = 负债 + 所有者权益 平衡校验，不平返回 diff 供前端红条警示。
    """
    tpl = _load_formula(db, "bs", BS_TEMPLATE)

    def build(section_key: str) -> dict:
        sec = tpl.get(section_key, {"label": section_key, "items": []})
        items = []
        for it in sec["items"]:
            amt = _balance_sum(db, book_id, it["accounts"], period_to)
            items.append({"name": it["name"], "accounts": it["accounts"], "amount": str(amt)})
        total = sum((Decimal(i["amount"]) for i in items), ZERO)
        return {"key": section_key, "label": sec.get("label", section_key),
                "items": items, "total": str(total)}

    asset_current = build("asset_current")
    asset_noncurrent = build("asset_noncurrent")
    liability_current = build("liability_current")
    liability_noncurrent = build("liability_noncurrent")
    equity = build("equity")

    total_assets = Decimal(asset_current["total"]) + Decimal(asset_noncurrent["total"])
    total_liabilities = Decimal(liability_current["total"]) + Decimal(liability_noncurrent["total"])
    total_equity = Decimal(equity["total"])
    diff = total_assets - (total_liabilities + total_equity)

    return {
        "period": period_to,
        "sections": {
            "asset_current": asset_current,
            "asset_noncurrent": asset_noncurrent,
            "liability_current": liability_current,
            "liability_noncurrent": liability_noncurrent,
            "equity": equity,
        },
        "total_assets": str(total_assets),
        "total_liabilities": str(total_liabilities),
        "total_equity": str(total_equity),
        "total_liab_equity": str(total_liabilities + total_equity),
        "balanced": diff == 0,
        "diff": str(diff),
        "warning": None if diff == 0 else
                   f"报表不平衡：资产合计 {total_assets} ≠ 负债和所有者权益合计 "
                   f"{total_liabilities + total_equity}，差额 {diff}",
    }


# ==================== 利润表 ====================

def income_statement(db: Session, book_id: int, period_from: str, period_to: str) -> dict:
    """利润表（期间发生额报表）。

    DoD ④：净利润应等于「本年利润(3103)」科目本期发生额。
    """
    tpl = _load_formula(db, "pl", PL_TEMPLATE)
    values: dict[str, Decimal] = {}
    rows = []

    for item in tpl:
        if item["type"] == "sum":
            sub = []
            total = ZERO
            for sub_it in item["items"]:
                amt = _period_amount(db, book_id, sub_it["accounts"], period_from, period_to)
                sub.append({"name": sub_it["name"], "accounts": sub_it["accounts"],
                            "amount": str(amt)})
                total += amt
            values[item["key"]] = total
            rows.append({"key": item["key"], "name": item["name"], "type": "sum",
                         "items": sub, "amount": str(total)})
        else:
            # formula: 支持 +/- 与已计算 key
            amt = _eval_expr(item["expr"], values)
            values[item["key"]] = amt
            rows.append({"key": item["key"], "name": item["name"], "type": "formula",
                         "expr": item["expr"], "items": [], "amount": str(amt)})

    net_profit = values.get("net_profit", ZERO)
    # DoD ④ 自检：本年利润科目本期发生额
    profit_acc = db.execute(
        select(AccountAccount).where(AccountAccount.book_id == book_id,
                                     AccountAccount.code == "3103",
                                     AccountAccount.active.is_(True))
    ).scalar_one_or_none()
    profit_move = ZERO
    if profit_acc:
        d, c = _line_sums(db, book_id, [profit_acc.id], period_from=period_from,
                          period_to=period_to)
        profit_move = c - d      # 本年利润是贷方方向：贷-借
    consistent = abs(net_profit - profit_move) < Decimal("0.01")

    return {
        "period_from": period_from, "period_to": period_to,
        "rows": rows,
        "net_profit": str(net_profit),
        "profit_account_move": str(profit_move),
        "consistent": consistent,
        "note": None if consistent else
                f"净利润 {net_profit} 与本年利润科目发生额 {profit_move} 不一致"
                f"（差额 {net_profit - profit_move}），通常是尚未做期末结转",
    }


def _eval_expr(expr: str, values: dict[str, Decimal]) -> Decimal:
    """计算极简表达式，只支持 `a + b - c` 形式（a/b/c 为已计算的项目 key）。"""
    total = ZERO
    sign = 1
    for token in expr.replace("+", " + ").replace("-", " - ").split():
        if token == "+":
            sign = 1
        elif token == "-":
            sign = -1
        else:
            total += sign * values.get(token.strip(), ZERO)
    return total
