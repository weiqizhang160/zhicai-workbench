# -*- coding: utf-8 -*-
"""银行流水服务：导入（编码容错 + 字段映射）/ 对账 / 月度汇总（项目书 6.8 / 7.8）。

各行导出的对账单表头五花八门（工行/建行/招行/农行），字段别名映射存 ir_config
（key = bank.import.field_map），用户可在「参数配置」里增改别名。

注意银行口径：debit = 收入（钱进账），credit = 支出（钱出账）。
"""
import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ..base.models import IrConfig
from ..invoice.service import decode_bytes
from .models import BankStatement, BankStatementLine

ZERO = Decimal("0.00")
TWO = Decimal("0.01")

FIELD_MAP_KEY = "bank.import.field_map"

# 默认字段别名（覆盖工行/建行/招行/农行常见导出版式）
DEFAULT_FIELD_MAP = {
    "trade_date": ["交易日期", "记账日期", "日期", "交易时间", "trade_date"],
    "trade_no": ["流水号", "交易流水号", "凭证号", "业务流水号", "trade_no"],
    "counterpart_name": ["对方户名", "对方账户名称", "对方名称", "收款人名称",
                         "付款人名称", "交易对手", "counterpart_name"],
    "summary": ["摘要", "交易摘要", "用途", "附言", "备注", "交易类型", "summary"],
    "debit": ["收入金额", "贷方发生额", "贷方金额", "收入", "存入金额", "debit"],
    "credit": ["支出金额", "借方发生额", "借方金额", "支出", "支出金额(元)", "credit"],
    "balance": ["余额", "账户余额", "交易后余额", "本次余额", "balance"],
}


def _d(v) -> Decimal:
    if v is None or v == "":
        return ZERO
    if isinstance(v, Decimal):
        return v
    s = str(v).strip().replace(",", "").replace("￥", "").replace("¥", "")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        val = Decimal(s or "0")
    except Exception:
        return ZERO
    return -val if neg else val


def _q(v: Decimal) -> Decimal:
    return v.quantize(TWO, rounding=__import__("decimal").ROUND_HALF_UP)


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _parse_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    if not s:
        raise BizError("date_required", "交易日期为空")
    s = s.replace("/", "-").replace(".", "-").replace("年", "-").replace("月", "-").replace("日", "")
    s = s.split(" ")[0]
    if len(s) == 8 and s.isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return date.fromisoformat(s[:10])


def load_field_map(db: Session) -> dict:
    row = db.execute(select(IrConfig).where(IrConfig.key == FIELD_MAP_KEY)).scalar_one_or_none()
    if row and row.value:
        try:
            loaded = json.loads(row.value)
            if isinstance(loaded, dict):
                return loaded
        except (ValueError, TypeError):
            pass
    return dict(DEFAULT_FIELD_MAP)


# ==================== 导入 ====================

def parse_bank_file(db: Session, raw: bytes, filename: str = "") -> tuple[list[dict], list[dict], str]:
    """解析银行对账单文件 → (合法行, 错误行, 识别到的编码)。

    编码容错：utf-8-sig → utf-8 → gb18030 → gbk（DoD 要求，防表头乱码）。
    """
    name = (filename or "").lower()
    encoding = ""
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        ws = wb[wb.sheetnames[0]]
        grid = [[c for c in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
        encoding = "xlsx"
    else:
        text, encoding = decode_bytes(raw)
        first = text.splitlines()[0] if text.splitlines() else ""
        delim = "," if first.count(",") >= first.count("\t") else "\t"
        if first.count(";") > max(first.count(","), first.count("\t")):
            delim = ";"
        grid = [r for r in csv.reader(io.StringIO(text), delimiter=delim)]

    if not grid:
        raise BizError("empty_file", "文件内容为空")

    # 找表头行（跳过银行对账单前几行的说明文字）
    fmap = load_field_map(db)
    head_idx, colmap = -1, {}
    for i, row in enumerate(grid[:15]):
        cells = [str(c or "").strip() for c in row]
        if not any(cells):
            continue
        tmp = {}
        for target, aliases in fmap.items():
            for j, cell in enumerate(cells):
                if cell in aliases:
                    tmp[j] = target
                    break
        # 至少识别出日期 + 一个金额列才算表头
        if "trade_date" in tmp.values() and (
                "debit" in tmp.values() or "credit" in tmp.values()):
            head_idx, colmap = i, tmp
            break
    if head_idx < 0:
        raise BizError("header_not_found",
                       "未识别到对账单表头（需要包含「交易日期」与「收入/支出金额」列）。"
                       "可在「参数配置」里维护 bank.import.field_map 增加别名")

    ok, errors = [], []
    for i in range(head_idx + 1, len(grid)):
        row = grid[i]
        if not any(str(c or "").strip() for c in row):
            continue
        item = {}
        for j, target in colmap.items():
            item[target] = row[j] if j < len(row) else None
        try:
            if not item.get("trade_date"):
                continue            # 无日期行（如合计行）跳过
            trade_date = _parse_date(item["trade_date"])
            debit = _q(_d(item.get("debit")))
            credit = _q(_d(item.get("credit")))
            if debit == 0 and credit == 0:
                continue            # 金额都为 0 的无效行
            ok.append({
                "trade_date": trade_date, "period": period_of(trade_date),
                "trade_no": (str(item["trade_no"]).strip() if item.get("trade_no") else None),
                "counterpart_name": (str(item["counterpart_name"]).strip()
                                     if item.get("counterpart_name") else None),
                "summary": (str(item["summary"]).strip() if item.get("summary") else None),
                "debit": debit, "credit": credit,
                "balance": (_q(_d(item["balance"])) if item.get("balance") else None),
            })
        except BizError as e:
            errors.append({"row": i + 1, "code": e.code, "message": e.message})
        except Exception as e:
            errors.append({"row": i + 1, "code": "parse_error", "message": str(e)[:120]})
    return ok, errors, encoding


def import_statement(db: Session, book_id: int, rows: list[dict], *,
                     bank_alias: str | None = None, account_no: str | None = None,
                     user_id: int | None = None) -> BankStatement:
    """建导入批次 + 写入流水行。"""
    if not rows:
        raise BizError("no_rows", "没有可导入的流水行")

    periods = sorted({r["period"] for r in rows})
    period = periods[0] if len(periods) == 1 else f"{periods[0]}~{periods[-1]}"
    total_debit = sum((r["debit"] for r in rows), ZERO)
    total_credit = sum((r["credit"] for r in rows), ZERO)
    now = datetime.now()

    stmt = BankStatement(
        bank_alias=bank_alias, account_no=account_no, period=period,
        imported_at=now, line_count=len(rows),
        total_debit=total_debit, total_credit=total_credit, book_id=book_id,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
    )
    db.add(stmt)
    db.flush()

    for r in rows:
        db.add(BankStatementLine(
            statement_id=stmt.id, trade_date=r["trade_date"], trade_no=r.get("trade_no"),
            counterpart_name=r.get("counterpart_name"), summary=r.get("summary"),
            debit=r["debit"], credit=r["credit"], balance=r.get("balance"),
            state="unreconciled", book_id=book_id,
            create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
        ))
    db.flush()
    return stmt


# ==================== 月度对账汇总（7.8） ====================

def month_summary(db: Session, book_id: int, period: str) -> dict:
    """期初余额 + 收入 - 支出 = 期末余额（与银行对账单核对）。"""
    rows = db.execute(
        select(BankStatementLine).where(
            BankStatementLine.book_id == book_id,
            BankStatementLine.active.is_(True),
            BankStatementLine.trade_date >= date(int(period[:4]), int(period[5:7]), 1),
            BankStatementLine.trade_date <= _month_end(period),
        ).order_by(BankStatementLine.trade_date, BankStatementLine.id)
    ).scalars().all()

    debit = sum((_d(l.debit) for l in rows), ZERO)
    credit = sum((_d(l.credit) for l in rows), ZERO)

    # 期初：本期之前最后一笔的余额；没有则取本期第一笔的余额反推
    opening = ZERO
    prev = db.execute(
        select(BankStatementLine).where(
            BankStatementLine.book_id == book_id, BankStatementLine.active.is_(True),
            BankStatementLine.trade_date < date(int(period[:4]), int(period[5:7]), 1),
            BankStatementLine.balance.isnot(None),
        ).order_by(BankStatementLine.trade_date.desc(), BankStatementLine.id.desc()).limit(1)
    ).scalar_one_or_none()
    if prev is not None:
        opening = _d(prev.balance)
    elif rows and rows[0].balance is not None:
        first = _d(rows[0].balance)
        opening = first - (_d(rows[0].debit) - _d(rows[0].credit))

    closing = opening + debit - credit
    return {
        "period": period, "count": len(rows),
        "opening": str(_q(opening)), "debit": str(_q(debit)), "credit": str(_q(credit)),
        "closing": str(_q(closing)),
        "reconciled": sum(1 for l in rows if l.state == "reconciled"),
        "unreconciled": sum(1 for l in rows if l.state == "unreconciled"),
    }


def _month_end(period: str) -> date:
    y, m = int(period[:4]), int(period[5:7])
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - __import__("datetime").timedelta(days=1)


def line_to_dict(ln: BankStatementLine) -> dict:
    return {
        "id": ln.id, "statement_id": ln.statement_id,
        "trade_date": ln.trade_date.isoformat() if ln.trade_date else None,
        "trade_no": ln.trade_no, "counterpart_name": ln.counterpart_name,
        "summary": ln.summary,
        "debit": str(_q(_d(ln.debit))), "credit": str(_q(_d(ln.credit))),
        "balance": (str(_q(_d(ln.balance))) if ln.balance is not None else None),
        "state": ln.state, "move_id": ln.move_id, "book_id": ln.book_id,
    }
