# -*- coding: utf-8 -*-
"""自动记账引擎（项目书 6.9 / 7.7）——本项目核心卖点。

流程：源单据 → 变量字典 → 规则匹配（match_condition，按 priority）→
     渲染 line_template（{字段} 变量 + =表达式）→ 借贷平衡校验 → 生成 draft 凭证 + 日志。

铁律：
1. 引擎必须保证生成的凭证借贷平衡，**不平衡整单拒绝并写日志**（项目书 6.9）；
2. 幂等由源单据自身状态保证（发票 entry_generated / 流水 reconciled），
   已处理的单据不再出现在待处理清单，重复执行不会重复生成（DoD）。
"""
import json
import re
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ..account.models import AccountAccount, AccountJournal
from ..account.move_service import create_move, period_of
from ..base.models import IrConfig
from ..bank.models import BankStatementLine
from ..invoice.models import InvoiceBill
from .models import AutoEntryLog, AutoEntryRule
from .seed_rules import CATEGORY_ACCOUNT_MAP_KEY, DEFAULT_CATEGORY_ACCOUNT_MAP

ZERO = Decimal("0.00")

SAFE_EXPR = re.compile(r"^[\d\.\s\+\-\*\/\(\)]+$")     # 表达式白名单（防 eval 注入）
VAR_PATTERN = re.compile(r"\{(\w+)\}")

# category 英文 key → 中文名（供模板 {category_label} 使用，避免摘要出现英文）
CATEGORY_LABELS = {
    "office": "办公费", "travel": "差旅费", "rent": "房租", "material": "材料采购",
    "entertain": "业务招待费", "utility": "水电物业", "telecom": "通讯网络",
    "logistics": "运输物流", "salary": "工资社保", "other": "其他费用",
}


def _d(v) -> Decimal:
    if v is None or v == "":
        return ZERO
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


# ==================== 源单据 → 变量字典 ====================

def source_to_dict(obj) -> dict:
    """把源单据转成模板可用的变量字典（日期/Decimal 转成字符串，便于替换）。"""
    if isinstance(obj, InvoiceBill):
        return {
            "id": obj.id, "direction": obj.direction, "invoice_type": obj.invoice_type,
            "invoice_code": obj.invoice_code or "", "invoice_no": obj.invoice_no,
            "invoice_date": obj.invoice_date.isoformat() if obj.invoice_date else "",
            "period": obj.period,
            "partner_name": obj.partner_name or "", "partner_tax_no": obj.partner_tax_no or "",
            "goods_amount": str(_d(obj.goods_amount)), "tax_amount": str(_d(obj.tax_amount)),
            "total_amount": str(_d(obj.total_amount)), "tax_rate": str(_d(obj.tax_rate)),
            "category": obj.category or "",
            "category_label": CATEGORY_LABELS.get(obj.category or "", obj.category or "费用"),
            "remark": obj.remark or "",
        }
    if isinstance(obj, BankStatementLine):
        return {
            "id": obj.id, "trade_date": obj.trade_date.isoformat() if obj.trade_date else "",
            "trade_no": obj.trade_no or "", "counterpart_name": obj.counterpart_name or "",
            "summary": obj.summary or "",
            "debit": str(_d(obj.debit)), "credit": str(_d(obj.credit)),
            "balance": str(_d(obj.balance)), "state": obj.state,
            # 流水场景常用别名，规则模板里可直接写 {amount}
            "amount": str(_d(obj.debit) if _d(obj.debit) > 0 else _d(obj.credit)),
        }
    raise BizError("unsupported_source", f"不支持的源单据类型：{type(obj).__name__}")


def trigger_of(source_model: str, obj) -> str:
    """源单据 → trigger 值。"""
    if source_model == "invoice_bill":
        return "invoice_output" if obj.direction == "output" else "invoice_input"
    if source_model == "bank_statement_line":
        return "bank_line"
    if source_model == "payroll_batch":
        return "payroll"
    raise BizError("unsupported_source", f"不支持的源单据：{source_model}")


# ==================== 规则匹配 ====================

def _field_value(src: dict, field: str):
    return src.get(field)


def matches_condition(cond: dict | None, src: dict) -> bool:
    """match_condition 求值。

    支持：
      {"invoice_type": "special"}          字段相等
      {"summary_ilike": "工资"}            字符串包含（忽略大小写）
      {"credit_gt": 0} / {"debit_gte": 100}  数值比较（_gt/_gte/_lt/_lte）
      {"direction_in": ["input", "output"]}   枚举包含
    """
    for key, expect in (cond or {}).items():
        if key.endswith("_ilike"):
            field = key[: -len("_ilike")]
            if str(expect).lower() not in str(_field_value(src, field) or "").lower():
                return False
        elif key.endswith(("_gt", "_gte", "_lt", "_lte")):
            op = key.rsplit("_", 1)[1]
            field = key[: -(len(op) + 1)]
            val = _d(_field_value(src, field))
            exp = _d(expect)
            if op == "gt" and not val > exp:
                return False
            if op == "gte" and not val >= exp:
                return False
            if op == "lt" and not val < exp:
                return False
            if op == "lte" and not val <= exp:
                return False
        elif key.endswith("_in"):
            field = key[: -len("_in")]
            vals = expect if isinstance(expect, (list, tuple)) else [expect]
            if _field_value(src, field) not in vals:
                return False
        else:
            if str(_field_value(src, key)) != str(expect):
                return False
    return True


def find_rules(db: Session, book_id: int, trigger: str) -> list[AutoEntryRule]:
    """取该账套 + 该触发源 的启用规则（含全局规则 book_id IS NULL），按优先级排序。"""
    rows = db.execute(
        select(AutoEntryRule).where(
            AutoEntryRule.active.is_(True),
            AutoEntryRule.enabled.is_(True),
            AutoEntryRule.trigger == trigger,
            (AutoEntryRule.book_id == book_id) | (AutoEntryRule.book_id.is_(None)),
        ).order_by(AutoEntryRule.priority, AutoEntryRule.id)
    ).scalars().all()
    return list(rows)


def match_rule(db: Session, book_id: int, trigger: str, src: dict) -> AutoEntryRule | None:
    """按 priority 找**第一个**命中的规则（小者优先）。"""
    for rule in find_rules(db, book_id, trigger):
        try:
            cond = json.loads(rule.match_condition) if rule.match_condition else {}
        except (ValueError, TypeError):
            cond = {}
        if matches_condition(cond, src):
            return rule
    return None


# ==================== 模板渲染 ====================

def _substitute_vars(text: str, src: dict) -> str:
    """把 {field} 替换成源单据值。"""
    def repl(m):
        name = m.group(1)
        return str(src.get(name, ""))
    return VAR_PATTERN.sub(repl, str(text or ""))


def _eval_amount(spec, src: dict) -> Decimal:
    """解析 amount 表达式。

    - "{total_amount}"     → 取字段值
    - "={goods_amount}*0.13" → 先替换变量再计算（字符集白名单校验后才 eval）
    - "100"                → 常量
    """
    s = str(spec if spec is not None else "").strip()
    if not s:
        return ZERO
    if s.startswith("="):
        expr = _substitute_vars(s[1:], src)
        if not SAFE_EXPR.match(expr):
            raise BizError("expr_unsafe", f"金额表达式含非法字符：{s}")
        try:
            return _d(eval(expr, {"__builtins__": {}}, {}))     # noqa: S307 已白名单校验
        except Exception as e:
            raise BizError("expr_error", f"金额表达式计算失败：{s}（{e}）")
    m = re.match(r"^\{(\w+)\}$", s)
    if m:
        return _d(src.get(m.group(1)))
    return _d(s)


def _category_account_map(db: Session) -> dict:
    row = db.execute(
        select(IrConfig).where(IrConfig.key == CATEGORY_ACCOUNT_MAP_KEY)
    ).scalar_one_or_none()
    if row and row.value:
        try:
            return json.loads(row.value) or {}
        except (ValueError, TypeError):
            pass
    return dict(DEFAULT_CATEGORY_ACCOUNT_MAP)


def _resolve_account(db: Session, book_id: int, spec, src: dict) -> AccountAccount:
    """科目解析：支持 "1122"、"1122 应收账款"、"{category_account}"。"""
    raw = _substitute_vars(str(spec or "").strip(), src)
    # 特殊变量 {category_account} 已在 _substitute_vars 阶段失败（src 里没有该 key），
    # 这里再单独处理：按 category 查映射表
    if raw.strip() == "" and "category_account" in str(spec):
        cmap = _category_account_map(db)
        cat = str(src.get("category") or "other")
        raw = cmap.get(cat) or cmap.get("other") or "6602.01"
    if not raw:
        raise BizError("account_empty", "分录模板缺少科目")
    code = raw.split()[0]        # "1122 应收账款" → "1122"
    acc = db.execute(
        select(AccountAccount).where(AccountAccount.book_id == book_id,
                                     AccountAccount.code == code,
                                     AccountAccount.active.is_(True))
    ).scalar_one_or_none()
    if acc is None:
        raise BizError("account_not_found", f"科目 {code} 不存在（账套内未找到该科目编码）")
    if not acc.is_leaf:
        raise BizError("account_not_leaf", f"科目 {code} {acc.name} 不是末级科目，不能记账")
    return acc


def render_lines(db: Session, book_id: int, rule: AutoEntryRule, src: dict) -> list[dict]:
    """渲染 line_template → 标准化分录（含科目 id 与借/贷金额）。"""
    try:
        tpl = json.loads(rule.line_template) if isinstance(rule.line_template, str) else rule.line_template
    except (ValueError, TypeError) as e:
        raise BizError("template_invalid", f"规则「{rule.name}」分录模板解析失败：{e}")

    if not isinstance(tpl, list) or not tpl:
        raise BizError("template_empty", f"规则「{rule.name}」分录模板为空")

    lines = []
    for i, item in enumerate(tpl, start=1):
        side = str(item.get("side") or "").lower()
        if side not in ("debit", "credit"):
            raise BizError("side_invalid", f"第 {i} 行：side 必须是 debit 或 credit")
        acc = _resolve_account(db, book_id, item.get("account"), src)
        amount = _eval_amount(item.get("amount"), src)
        summary = _substitute_vars(item.get("summary") or "", src).strip()
        if amount < 0:
            raise BizError("amount_negative", f"第 {i} 行：金额不能为负数（{amount}）")
        lines.append({
            "side": side, "account_id": acc.id,
            "account_code": acc.code, "account_name": acc.name,
            "summary": summary or acc.name,
            "debit": str(amount) if side == "debit" else "0",
            "credit": str(amount) if side == "credit" else "0",
        })
    return lines


def check_balanced(lines: list[dict]) -> tuple[Decimal, Decimal]:
    """借贷平衡校验（项目书 6.9 铁律）。不平衡抛 BizError。"""
    td = sum((_d(l["debit"]) for l in lines), ZERO)
    tc = sum((_d(l["credit"]) for l in lines), ZERO)
    if td != tc:
        raise BizError("template_unbalanced",
                       f"模板生成凭证借贷不平衡：借方合计 {td}，贷方合计 {tc}，差额 {td - tc}")
    if td <= 0:
        raise BizError("template_zero_amount", "模板生成凭证金额为 0，已拒绝")
    return td, tc


# ==================== 预览（不落库） ====================

def preview_for_source(db: Session, book_id: int, source_model: str, obj) -> dict:
    """单条源单据的匹配结果 + 分录预览（批量执行工作台的数据源）。"""
    src = source_to_dict(obj)
    trigger = trigger_of(source_model, obj)
    rule = match_rule(db, book_id, trigger, src)
    base = {
        "source_model": source_model, "source_id": obj.id,
        "trigger": trigger, "source": src,
        "rule_id": rule.id if rule else None,
        "rule_name": rule.name if rule else None,
        "matched": rule is not None,
        "lines": [], "total_debit": "0.00", "total_credit": "0.00", "error": None,
    }
    if not rule:
        base["error"] = "未匹配到规则（留在待人工清单）"
        return base
    try:
        lines = render_lines(db, book_id, rule, src)
        td, tc = check_balanced(lines)
        base["lines"] = lines
        base["total_debit"] = str(td)
        base["total_credit"] = str(tc)
    except BizError as e:
        base["matched"] = False
        base["error"] = e.message
        base["error_code"] = e.code
    return base


def collect_pending(db: Session, book_id: int, period: str | None = None,
                    source_models: list[str] | None = None) -> list[dict]:
    """列出所有未生成凭证的源单据 + 预览（DoD：批量执行工作台）。"""
    models = source_models or ["invoice_bill", "bank_statement_line"]
    out = []
    if "invoice_bill" in models:
        q = select(InvoiceBill).where(
            InvoiceBill.book_id == book_id, InvoiceBill.active.is_(True),
            InvoiceBill.state == "registered")
        if period:
            q = q.where(InvoiceBill.period == period)
        for inv in db.execute(q.order_by(InvoiceBill.invoice_date, InvoiceBill.id)).scalars().all():
            out.append(preview_for_source(db, book_id, "invoice_bill", inv))
    if "bank_statement_line" in models:
        q = select(BankStatementLine).where(
            BankStatementLine.book_id == book_id, BankStatementLine.active.is_(True),
            BankStatementLine.state == "unreconciled")
        if period:
            q = q.where(BankStatementLine.trade_date >= _period_start(period),
                        BankStatementLine.trade_date <= _period_end(period))
        for ln in db.execute(q.order_by(BankStatementLine.trade_date,
                                        BankStatementLine.id)).scalars().all():
            out.append(preview_for_source(db, book_id, "bank_statement_line", ln))
    return out


def _period_start(period: str) -> date:
    y, m = int(period[:4]), int(period[5:7])
    return date(y, m, 1)


def _period_end(period: str) -> date:
    y, m = int(period[:4]), int(period[5:7])
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - __import__("datetime").timedelta(days=1)


# ==================== 执行 ====================

def _load_source(db: Session, source_model: str, source_id: int):
    cls = {"invoice_bill": InvoiceBill, "bank_statement_line": BankStatementLine}.get(source_model)
    if cls is None:
        raise BizError("unsupported_source", f"不支持的源单据：{source_model}")
    obj = db.get(cls, source_id)
    if obj is None or not obj.active:
        raise BizError("source_not_found", "源单据不存在")
    return obj


def _write_log(db: Session, *, book_id: int, rule_id, source_model: str, source_id: int,
               result: str, move_id=None, message: str | None = None):
    db.add(AutoEntryLog(rule_id=rule_id, source_model=source_model, source_id=source_id,
                        result=result, move_id=move_id, message=message,
                        created_at=datetime.now(), book_id=book_id,
                        create_date=datetime.now(), active=True))


def execute_one(db: Session, book_id: int, source_model: str, source_id: int,
                rule_id: int | None = None, user_id: int | None = None,
                override_lines: list[dict] | None = None) -> dict:
    """为单条源单据生成凭证（draft）。

    幂等：源单据已处理（发票 entry_generated / 流水 reconciled）则直接跳过。
    """
    obj = _load_source(db, source_model, source_id)
    src = source_to_dict(obj)
    trigger = trigger_of(source_model, obj)

    # —— 幂等闸门 ——
    if source_model == "invoice_bill" and not obj.can_generate_entry:
        return {"ok": False, "skipped": True, "result": "skipped",
                "message": f"发票 {obj.invoice_no} 状态为 {obj.state}，已跳过"}
    if source_model == "bank_statement_line" and not obj.can_generate_entry:
        return {"ok": False, "skipped": True, "result": "skipped",
                "message": f"流水 #{obj.id} 已对账，已跳过"}

    # 规则：优先用指定规则，否则自动匹配
    if rule_id:
        rule = db.get(AutoEntryRule, rule_id)
        if rule is None:
            raise BizError("rule_not_found", "规则不存在")
    else:
        rule = match_rule(db, book_id, trigger, src)
    if rule is None:
        _write_log(db, book_id=book_id, rule_id=None, source_model=source_model,
                   source_id=source_id, result="skipped", message="未匹配到规则")
        db.flush()
        return {"ok": False, "skipped": True, "result": "skipped", "message": "未匹配到规则"}

    try:
        lines = override_lines if override_lines else render_lines(db, book_id, rule, src)
        check_balanced(lines)
    except BizError as e:
        _write_log(db, book_id=book_id, rule_id=rule.id, source_model=source_model,
                   source_id=source_id, result="failed", message=e.message)
        db.flush()
        return {"ok": False, "result": "failed", "message": e.message, "code": e.code}

    # 凭证字
    journal = db.execute(
        select(AccountJournal).where(AccountJournal.book_id == book_id,
                                     AccountJournal.code == (rule.journal_code or "记"),
                                     AccountJournal.active.is_(True))
    ).scalar_one_or_none()
    if journal is None:
        journal = db.execute(
            select(AccountJournal).where(AccountJournal.book_id == book_id,
                                         AccountJournal.active.is_(True))
            .order_by(AccountJournal.id)).scalars().first()
    if journal is None:
        raise BizError("no_journal", "该账套没有凭证字（账簿），无法生成凭证")

    move_date = obj.invoice_date if source_model == "invoice_bill" else obj.trade_date
    try:
        move = create_move(
            db, book_id=book_id, journal_id=journal.id, move_date=move_date,
            lines=[{"summary": l["summary"], "account_id": l["account_id"],
                    "debit": l["debit"], "credit": l["credit"]} for l in lines],
            source_type="auto_invoice" if source_model == "invoice_bill" else "auto_bank",
            user_id=user_id,
            remark=f"自动记账：{rule.name}（{source_model}#{source_id}）",
        )
    except BizError as e:
        _write_log(db, book_id=book_id, rule_id=rule.id, source_model=source_model,
                   source_id=source_id, result="failed", message=e.message)
        db.flush()
        return {"ok": False, "result": "failed", "message": e.message, "code": e.code}

    # 回写源单据状态（幂等的依据）
    if source_model == "invoice_bill":
        obj.state = "entry_generated"
        obj.move_id = move.id
    else:
        obj.state = "reconciled"
        obj.move_id = move.id
    obj.write_uid = user_id
    obj.write_date = datetime.now()

    _write_log(db, book_id=book_id, rule_id=rule.id, source_model=source_model,
               source_id=source_id, result="ok", move_id=move.id,
               message=f"生成凭证 #{move.id}")
    db.flush()
    return {"ok": True, "result": "ok", "move_id": move.id,
            "rule_id": rule.id, "rule_name": rule.name,
            "source_model": source_model, "source_id": source_id}


def execute_batch(db: Session, book_id: int, items: list[dict],
                  user_id: int | None = None) -> dict:
    """批量执行：逐条独立处理（单条失败不影响其他），返回成功/失败/跳过明细。"""
    ok, failed, skipped = [], [], []
    for it in items:
        try:
            res = execute_one(db, book_id, it.get("source_model"), int(it.get("source_id")),
                              rule_id=it.get("rule_id"), user_id=user_id,
                              override_lines=it.get("lines"))
        except BizError as e:
            failed.append({"source_model": it.get("source_model"),
                           "source_id": it.get("source_id"), "message": e.message})
            continue
        except Exception as e:      # 兜底：不让一条脏数据炸掉整批
            failed.append({"source_model": it.get("source_model"),
                           "source_id": it.get("source_id"), "message": str(e)[:200]})
            continue
        if res.get("ok"):
            ok.append(res)
        elif res.get("skipped"):
            skipped.append(res)
        else:
            failed.append(res)
    db.flush()
    return {"ok": len(ok), "failed": len(failed), "skipped": len(skipped),
            "details": {"ok": ok, "failed": failed, "skipped": skipped}}
