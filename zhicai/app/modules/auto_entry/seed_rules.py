# -*- coding: utf-8 -*-
"""内置种子自动记账规则（项目书 6.9 第 1-6 条）。

规则设计要点：
- account 一律用**科目代码**（科目名称可改，代码稳定）；引擎也兼容"代码 名称"写法；
- amount 支持 {字段} 变量与 =表达式（如 ={goods_amount}*0.13）；
- 进项发票的费用科目用特殊变量 {category_account}，由 category→科目映射表
  （ir_config: auto_entry.category_account_map）动态解析；
- 优先级数字小者优先：工资(10) < 税(20) < 收款(30)，避免"代扣个税"被收款规则误命中。
"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..base.models import IrConfig
from ..res_partner.models import ResBook
from .models import AutoEntryRule

# category → 费用科目代码映射（存 ir_config，用户可在「参数配置」里改）
CATEGORY_ACCOUNT_MAP_KEY = "auto_entry.category_account_map"
DEFAULT_CATEGORY_ACCOUNT_MAP = {
    "office": "6602.01",      # 办公费
    "travel": "6602.02",      # 差旅费
    "rent": "6602.04",        # 房租
    "material": "1405",       # 材料采购 → 库存商品
    "entertain": "6602.03",   # 业务招待费
    "utility": "6602.05",     # 水电物业
    "telecom": "6602.06",     # 通讯网络
    "logistics": "6601.04",   # 运输物流 → 销售费用
    "salary": "6602.07",      # 工资
    "other": "6602.01",       # 其他（默认归办公费，可在参数配置调整）
}

# 种子规则定义：(seed_key, dict)
SEED_RULES = [
    {
        "seed_key": "out_invoice_revenue",
        "name": "销项发票 → 确认收入",
        "trigger": "invoice_output",
        "match_condition": {},
        "journal_code": "记",
        "priority": 10,
        "line_template": [
            {"side": "debit", "account": "1122", "summary": "应收 {partner_name}",
             "amount": "{total_amount}"},
            {"side": "credit", "account": "6001", "summary": "销售收入 {partner_name}",
             "amount": "{goods_amount}"},
            {"side": "credit", "account": "2221.01.01", "summary": "销项税额",
             "amount": "{tax_amount}"},
        ],
    },
    {
        "seed_key": "in_invoice_expense",
        "name": "进项发票 → 费用/采购入账",
        "trigger": "invoice_input",
        "match_condition": {},
        "journal_code": "记",
        "priority": 10,
        "line_template": [
            {"side": "debit", "account": "{category_account}",
             "summary": "{category_label} {partner_name}", "amount": "{goods_amount}"},
            {"side": "debit", "account": "2221.01.02", "summary": "进项税额",
             "amount": "{tax_amount}"},
            {"side": "credit", "account": "2202", "summary": "应付 {partner_name}",
             "amount": "{total_amount}"},
        ],
    },
    {
        "seed_key": "bank_salary_payment",
        "name": "银行流水「工资」支出 → 冲应付职工薪酬",
        "trigger": "bank_line",
        "match_condition": {"summary_ilike": "工资", "credit_gt": 0},
        "journal_code": "记",
        "priority": 10,
        "line_template": [
            {"side": "debit", "account": "2211.01", "summary": "支付工资 {counterpart_name}",
             "amount": "{credit}"},
            {"side": "credit", "account": "1002", "summary": "支付工资", "amount": "{credit}"},
        ],
    },
    {
        "seed_key": "bank_tax_payment",
        "name": "银行流水「税」支出 → 缴纳增值税",
        "trigger": "bank_line",
        "match_condition": {"summary_ilike": "税", "credit_gt": 0},
        "journal_code": "记",
        "priority": 20,
        "line_template": [
            {"side": "debit", "account": "2221.02", "summary": "缴纳税款 {counterpart_name}",
             "amount": "{credit}"},
            {"side": "credit", "account": "1002", "summary": "缴纳税款", "amount": "{credit}"},
        ],
    },
    {
        "seed_key": "bank_receipt",
        "name": "银行流水收入 → 收回应收账款",
        "trigger": "bank_line",
        "match_condition": {"debit_gt": 0},
        "journal_code": "记",
        "priority": 30,
        "line_template": [
            {"side": "debit", "account": "1002", "summary": "收到 {counterpart_name}",
             "amount": "{debit}"},
            {"side": "credit", "account": "1122", "summary": "收回货款 {counterpart_name}",
             "amount": "{debit}"},
        ],
    },
    {
        "seed_key": "payroll_accrual",
        "name": "工资批次 → 计提与发放（M6 启用）",
        "trigger": "payroll",
        "match_condition": {},
        "journal_code": "记",
        "priority": 10,
        "enabled": False,      # M6 交付工资模块后再启用
        "line_template": [
            {"side": "debit", "account": "6602.07", "summary": "计提工资", "amount": "{total_amount}"},
            {"side": "credit", "account": "2211.01", "summary": "应付工资", "amount": "{total_amount}"},
        ],
    },
]


def _ensure_category_map_config(db: Session, book_id: int | None = None) -> None:
    """写入 category→科目 映射表到 ir_config（幂等，已存在则不动）。"""
    row = db.execute(
        select(IrConfig).where(IrConfig.key == CATEGORY_ACCOUNT_MAP_KEY)
    ).scalar_one_or_none()
    if row is None:
        db.add(IrConfig(key=CATEGORY_ACCOUNT_MAP_KEY,
                        value=json.dumps(DEFAULT_CATEGORY_ACCOUNT_MAP, ensure_ascii=False)))
        db.flush()


def seed_rules_for_book(db: Session, book_id: int) -> int:
    """为指定账套创建缺失的种子规则（幂等：按 seed_key 判断，已存在则跳过）。

    返回新建条数。
    """
    _ensure_category_map_config(db, book_id)

    existed = {
        r[0] for r in db.execute(
            select(AutoEntryRule.seed_key).where(AutoEntryRule.book_id == book_id)
        ).all()
    }
    created = 0
    for spec in SEED_RULES:
        if spec["seed_key"] in existed:
            continue
        db.add(AutoEntryRule(
            name=spec["name"], trigger=spec["trigger"],
            match_condition=json.dumps(spec.get("match_condition", {}), ensure_ascii=False),
            journal_code=spec.get("journal_code", "记"),
            line_template=json.dumps(spec["line_template"], ensure_ascii=False),
            priority=spec.get("priority", 100),
            enabled=spec.get("enabled", True),
            is_seed=True, seed_key=spec["seed_key"], book_id=book_id,
        ))
        created += 1
    if created:
        db.flush()
    return created


def seed_rules(db: Session) -> None:
    """模块级种子：为所有已存在的账套补建规则（启动/新账套后均可调用，幂等）。"""
    books = db.execute(select(ResBook.id).where(ResBook.active.is_(True))).scalars().all()
    for book_id in books:
        seed_rules_for_book(db, book_id)
    db.flush()


def refresh_seed_rules(db: Session, book_id: int | None = None) -> int:
    """把内置种子规则的定义（模板/名称/优先级）同步到已有规则。

    注意：**会覆盖** is_seed=True 规则的模板定义，但保留用户调整过的
    enabled（启停）与 priority 之外的自定义？——不，priority 也同步。
    仅在升级种子规则定义后手工调用，避免用户自定义规则被误改。
    """
    q = select(AutoEntryRule).where(AutoEntryRule.is_seed.is_(True),
                                    AutoEntryRule.active.is_(True))
    if book_id is not None:
        q = q.where(AutoEntryRule.book_id == book_id)
    rules = db.execute(q).scalars().all()
    # 注意：不能用 {seed_key: rule} 字典去重——多个账套各有同 seed_key 的规则，
    # 去重后只有最后一条会被更新（曾导致只有最后一个账套生效）。
    spec_by_key = {spec["seed_key"]: spec for spec in SEED_RULES}
    updated = 0
    for r in rules:
        spec = spec_by_key.get(r.seed_key)
        if spec is None:
            continue
        r.name = spec["name"]
        r.trigger = spec["trigger"]
        r.line_template = json.dumps(spec["line_template"], ensure_ascii=False)
        r.priority = spec.get("priority", 100)
        updated += 1
    if updated:
        db.flush()
    return updated
