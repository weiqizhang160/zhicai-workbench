# -*- coding: utf-8 -*-
"""个税计算（项目书 6.12 / 7.11）：月度预扣率表 + 累计预扣法，税率表存 ir_config 可更新。

税率表口径（2026 现行个税法，年度综合所得税率表按月换算）：
- 月度预扣率表（工资薪金按月预扣 / 年终奖单独计税同表）；
- 累计预扣法：本期应预扣 = (累计应纳税所得额 × 税率 − 速算扣除) − 已预扣合计。

MVP 简化（项目书明确允许）：批次默认按「月度表 × 单月应纳税所得额」计算，
允许前端手工覆盖 iit 值；跨月累计差额可通过累计接口补算。
"""
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ..base.models import IrConfig

IIT_BRACKETS_KEY = "payroll.iit_brackets"

ZERO = Decimal("0.00")

# 月度预扣率表：[(上限, 税率, 速算扣除数)]，上限 -1 = 无穷
MONTHLY_BRACKETS = [
    {"upper": 3000, "rate": 0.03, "deduction": 0},
    {"upper": 12000, "rate": 0.10, "deduction": 210},
    {"upper": 25000, "rate": 0.20, "deduction": 1410},
    {"upper": 35000, "rate": 0.25, "deduction": 2660},
    {"upper": 55000, "rate": 0.30, "deduction": 4410},
    {"upper": 80000, "rate": 0.35, "deduction": 7160},
    {"upper": None, "rate": 0.45, "deduction": 15160},
]

# 基本减除费用（5000 元/月）
BASIC_DEDUCTION = Decimal("5000")


def ensure_brackets(db: Session) -> None:
    row = db.execute(select(IrConfig).where(IrConfig.key == IIT_BRACKETS_KEY)
                     ).scalar_one_or_none()
    if row is None:
        db.add(IrConfig(key=IIT_BRACKETS_KEY,
                        value=json.dumps(MONTHLY_BRACKETS, ensure_ascii=False),
                        remark="个税月度预扣率表（可更新，上限 null=无上限）"))
        db.flush()


def load_brackets(db: Session) -> list[dict]:
    ensure_brackets(db)
    row = db.execute(select(IrConfig).where(IrConfig.key == IIT_BRACKETS_KEY)).scalar_one()
    try:
        data = json.loads(row.value or "[]")
    except (ValueError, TypeError):
        data = []
    if not data:
        return MONTHLY_BRACKETS
    # 规范化：Decimal 化
    out = []
    for b in data:
        out.append({
            "upper": (Decimal(str(b["upper"])) if b.get("upper") is not None else None),
            "rate": Decimal(str(b["rate"])),
            "deduction": Decimal(str(b.get("deduction", 0))),
        })
    return out


def _bracket_for(brackets: list[dict], taxable: Decimal) -> dict:
    """应纳税所得额 → 命中的税率档。"""
    for b in brackets:
        upper = b["upper"]
        if upper is None or taxable <= Decimal(str(upper)):
            return b
    return brackets[-1]


def _round_tax(v: Decimal) -> Decimal:
    """税额保留 2 位（四舍五入）。"""
    return v.quantize(Decimal("0.01"))


def compute_iit_monthly(gross, social_employee, brackets: list[ dict] | None = None) -> Decimal:
    """月度简化计算：应纳税所得额 = 应发 − 5000 − 个人社保；≤0 不征税。

    brackets 缺省用内置月度表（测试传自定义表验证边界值）。
    """
    brackets = brackets or [
        {"upper": Decimal(str(b["upper"])) if b["upper"] is not None else None,
         "rate": Decimal(str(b["rate"])), "deduction": Decimal(str(b["deduction"]))}
        for b in MONTHLY_BRACKETS
    ]
    taxable = Decimal(str(gross or 0)) - BASIC_DEDUCTION - Decimal(str(social_employee or 0))
    if taxable <= 0:
        return ZERO
    b = _bracket_for(brackets, taxable)
    return _round_tax(taxable * b["rate"] - b["deduction"])


def compute_iit_cumulative(cum_income, cum_social, cum_withheld,
                           months: int = 1, brackets: list[dict] | None = None) -> Decimal:
    """累计预扣法：本期应预扣 = 累计应预扣 − 已预扣。

    cum_income/cum_social 为年初至本期累计（含本期），months 为累计月份数，
    cum_withheld 为年初至上期已预扣合计。
    """
    brackets = brackets or [
        {"upper": Decimal(str(b["upper"])) * 12 if b["upper"] is not None else None,
         "rate": Decimal(str(b["rate"])), "deduction": Decimal(str(b["deduction"])) * 12}
        for b in MONTHLY_BRACKETS
    ]
    taxable = (Decimal(str(cum_income or 0))
               - BASIC_DEDUCTION * max(int(months), 1)
               - Decimal(str(cum_social or 0)))
    if taxable <= 0:
        cum_tax = ZERO
    else:
        b = _bracket_for(brackets, taxable)
        cum_tax = _round_tax(taxable * b["rate"] - b["deduction"])
    return max(_round_tax(cum_tax - Decimal(str(cum_withheld or 0))), ZERO)
