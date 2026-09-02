# -*- coding: utf-8 -*-
"""内置征期规则种子（项目书 6.10）。

- vat：小规模→按季（次季首月 15 日）；一般纳税人→按月（次月 15 日）
- cit：季度预缴（次季首月 15 日）+ 年度汇算（次年 5 月 31 日）
- iit：按月（次月 15 日）
- 印花税：按季（次季首月 15 日）
- 附加税：随增值税（与增值税同频率，因为计税依据是实缴增值税）
"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import TaxCalendarRule

SEED_RULES = [
    {
        "seed_key": "vat_small",
        "name": "增值税（小规模·按季）",
        "tax_kind": "vat", "period_type": "quarterly",
        "deadline_rule": "quarter_next_month_15",
        "applies_to": {"taxpayer_type": "small"},
    },
    {
        "seed_key": "vat_general",
        "name": "增值税（一般纳税人·按月）",
        "tax_kind": "vat", "period_type": "monthly",
        "deadline_rule": "next_month_15",
        "applies_to": {"taxpayer_type": "general"},
    },
    {
        "seed_key": "surtax_small",
        "name": "附加税（小规模·按季）",
        "tax_kind": "surtax", "period_type": "quarterly",
        "deadline_rule": "quarter_next_month_15",
        "applies_to": {"taxpayer_type": "small"},
    },
    {
        "seed_key": "surtax_general",
        "name": "附加税（一般纳税人·按月）",
        "tax_kind": "surtax", "period_type": "monthly",
        "deadline_rule": "next_month_15",
        "applies_to": {"taxpayer_type": "general"},
    },
    {
        "seed_key": "cit_quarterly",
        "name": "企业所得税（季度预缴）",
        "tax_kind": "cit_quarterly", "period_type": "quarterly",
        "deadline_rule": "quarter_next_month_15",
        "applies_to": None,      # 全部账套
    },
    {
        "seed_key": "cit_annual",
        "name": "企业所得税（年度汇算）",
        "tax_kind": "cit_annual", "period_type": "yearly",
        "deadline_rule": "annual_0531",
        "applies_to": None,
    },
    {
        "seed_key": "iit_monthly",
        "name": "个人所得税（工资薪金·按月）",
        "tax_kind": "iit", "period_type": "monthly",
        "deadline_rule": "next_month_15",
        "applies_to": None,
    },
    {
        "seed_key": "stamp_quarterly",
        "name": "印花税（买卖合同·按季）",
        "tax_kind": "stamp", "period_type": "quarterly",
        "deadline_rule": "quarter_next_month_15",
        "applies_to": None,
    },
]


def seed_calendar_rules(db: Session) -> int:
    """写入缺失的征期规则（按 seed_key 幂等）。已存在则不动。"""
    existed = {
        r[0] for r in db.execute(
            select(TaxCalendarRule.seed_key).where(TaxCalendarRule.active.is_(True))
        ).all()
    }
    created = 0
    for spec in SEED_RULES:
        if spec["seed_key"] in existed:
            continue
        db.add(TaxCalendarRule(
            name=spec["name"], tax_kind=spec["tax_kind"],
            period_type=spec["period_type"], deadline_rule=spec["deadline_rule"],
            applies_to=json.dumps(spec["applies_to"], ensure_ascii=False)
            if spec["applies_to"] else None,
            enabled=True, is_seed=True, seed_key=spec["seed_key"], active=True,
        ))
        created += 1
    if created:
        db.flush()
    return created
