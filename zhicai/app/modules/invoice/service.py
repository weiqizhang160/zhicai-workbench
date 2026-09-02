# -*- coding: utf-8 -*-
"""发票服务：价税合计计算 / 查重 / Excel-CSV 导入 / 月末视图（项目书 6.7 / 7.6）。

金额一律 Decimal（禁 float），保留 2 位、ROUND_HALF_UP——DoD 要求价税合计精度正确。
"""
import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from .models import InvoiceBill

TWO = Decimal("0.01")
ZERO = Decimal("0.00")


def _d(v) -> Decimal:
    if v is None or v == "":
        return ZERO
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _q(v: Decimal) -> Decimal:
    """金额统一 2 位小数、四舍五入。"""
    return v.quantize(TWO, rounding=ROUND_HALF_UP)


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _parse_date(v) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v or "").strip()
    if not s:
        raise BizError("date_required", "开票日期不能为空")
    s = s.replace("/", "-").replace(".", "-")
    # 兼容 20260901 / 2026-09-01 / 2026年9月1日
    if len(s) == 8 and s.isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    s = s.replace("年", "-").replace("月", "-").replace("日", "")
    return date.fromisoformat(s[:10])


# ==================== 价税合计（DoD：Decimal 精度正确） ====================

def _opt(v):
    """把「0 / 空」视为未提供。

    必需：否则前端传 goods_amount="0"（默认占位）时会被当成"已知不含税=0"，
    导致价税合计反算分支失效，算出 goods=0 / tax=0 / total=1130 的畸形数据。
    """
    if v in (None, "", 0, "0", "0.0", "0.00", "0.0000"):
        return None
    return v


def compute_amounts(*, goods=None, tax=None, total=None, rate=None) -> tuple[Decimal, Decimal, Decimal]:
    """价税三者知二求一（goods + tax = total）。

    优先级：
      1) goods & rate  → tax = goods*rate,  total = goods+tax
      2) goods & tax   → total = goods+tax
      3) total & rate  → goods = total/(1+rate), tax = total-goods（含税价反算）
      4) total & tax   → goods = total-tax
      5) 仅 goods      → tax=0, total=goods
    返回 (goods_amount, tax_amount, total_amount)，均为 2 位 Decimal。
    """
    g = _d(goods) if goods not in (None, "") else None
    t = _d(tax) if tax not in (None, "") else None
    tt = _d(total) if total not in (None, "") else None
    r = _d(rate) if rate not in (None, "") else None

    if g is not None and r is not None and t is None:
        t = _q(g * r)
    if g is not None and t is None and tt is not None:
        t = _q(tt - g)
    if tt is not None and r is not None and g is None:
        if r == Decimal("-1"):
            raise BizError("rate_invalid", "税率不能为 -1")
        g = _q(tt / (Decimal("1") + r))
        t = _q(tt - g)
    if g is None and tt is not None and t is not None:
        g = _q(tt - t)
    g = g if g is not None else ZERO
    t = t if t is not None else ZERO
    if tt is None:
        tt = _q(g + t)
    return _q(g), _q(t), _q(tt)


# ==================== 查重（DoD：重复发票拦截） ====================

def find_duplicate(db: Session, book_id: int, invoice_code: str | None, invoice_no: str,
                   invoice_date: date, exclude_id: int | None = None):
    """同账套内 代码+号码+日期 重复即视为重复票。"""
    q = select(InvoiceBill).where(
        InvoiceBill.book_id == book_id,
        InvoiceBill.active.is_(True),
        InvoiceBill.invoice_no == str(invoice_no).strip(),
        InvoiceBill.invoice_date == invoice_date,
        InvoiceBill.invoice_code == (str(invoice_code).strip() if invoice_code else None),
    )
    if exclude_id:
        q = q.where(InvoiceBill.id != exclude_id)
    return db.execute(q).scalars().first()


# ==================== 单张增删改 ====================

def create_invoice(db: Session, book_id: int, data: dict, user_id: int | None = None) -> InvoiceBill:
    invoice_no = str(data.get("invoice_no") or "").strip()
    if not invoice_no:
        raise BizError("invoice_no_required", "发票号码不能为空")
    idate = _parse_date(data.get("invoice_date"))

    dup = find_duplicate(db, book_id, data.get("invoice_code"), invoice_no, idate)
    if dup:
        raise BizError("invoice_duplicate",
                       f"发票重复：{invoice_no}（{idate}）已在系统中登记过")

    goods, tax, total = compute_amounts(
        goods=_opt(data.get("goods_amount")), tax=_opt(data.get("tax_amount")),
        total=_opt(data.get("total_amount")), rate=_opt(data.get("tax_rate")))

    now = datetime.now()
    inv = InvoiceBill(
        direction=data.get("direction") or "input",
        invoice_type=data.get("invoice_type") or "special",
        invoice_code=(str(data["invoice_code"]).strip() if data.get("invoice_code") else None),
        invoice_no=invoice_no,
        invoice_date=idate, period=period_of(idate),
        partner_name=data.get("partner_name"), partner_tax_no=data.get("partner_tax_no"),
        partner_id=data.get("partner_id"),
        goods_amount=goods, tax_amount=tax, total_amount=total,
        tax_rate=_d(data.get("tax_rate")),
        category=data.get("category"), state="registered",
        remark=data.get("remark"), source=data.get("source") or "manual",
        book_id=book_id,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
    )
    db.add(inv)
    db.flush()
    return inv


def update_invoice(db: Session, inv: InvoiceBill, data: dict,
                   user_id: int | None = None) -> InvoiceBill:
    if inv.state == "entry_generated":
        raise BizError("invoice_locked", "已生成凭证的发票不能修改，请先删除对应凭证")
    idate = _parse_date(data.get("invoice_date", inv.invoice_date))
    inv.invoice_date = idate
    inv.period = period_of(idate)
    inv.invoice_code = str(data["invoice_code"]).strip() if data.get("invoice_code") else None
    inv.invoice_no = str(data.get("invoice_no") or inv.invoice_no).strip()
    inv.direction = data.get("direction", inv.direction)
    inv.invoice_type = data.get("invoice_type", inv.invoice_type)
    inv.partner_name = data.get("partner_name", inv.partner_name)
    inv.partner_tax_no = data.get("partner_tax_no", inv.partner_tax_no)
    inv.partner_id = data.get("partner_id", inv.partner_id)
    inv.category = data.get("category", inv.category)
    inv.remark = data.get("remark", inv.remark)

    g, t, tt = compute_amounts(
        goods=data.get("goods_amount", inv.goods_amount),
        tax=data.get("tax_amount", inv.tax_amount),
        total=data.get("total_amount"),
        rate=data.get("tax_rate", inv.tax_rate))
    inv.goods_amount, inv.tax_amount, inv.total_amount = g, t, tt
    if data.get("tax_rate") is not None:
        inv.tax_rate = _d(data["tax_rate"])

    inv.write_uid = user_id
    inv.write_date = datetime.now()
    db.flush()
    return inv


# ==================== 导入（Excel / CSV） ====================

# 中文表头 → 字段（同时兼容英文）
HEADER_ALIASES = {
    "方向": "direction", "direction": "direction",
    "票种": "invoice_type", "发票类型": "invoice_type", "invoice_type": "invoice_type",
    "发票代码": "invoice_code", "代码": "invoice_code", "invoice_code": "invoice_code",
    "发票号码": "invoice_no", "号码": "invoice_no", "发票号": "invoice_no",
    "invoice_no": "invoice_no",
    "开票日期": "invoice_date", "日期": "invoice_date", "invoice_date": "invoice_date",
    "对方名称": "partner_name", "销方名称": "partner_name", "购方名称": "partner_name",
    "客户名称": "partner_name", "partner_name": "partner_name",
    "对方税号": "partner_tax_no", "纳税人识别号": "partner_tax_no",
    "partner_tax_no": "partner_tax_no",
    "不含税金额": "goods_amount", "金额": "goods_amount", "goods_amount": "goods_amount",
    "税额": "tax_amount", "tax_amount": "tax_amount",
    "税率": "tax_rate", "tax_rate": "tax_rate",
    "价税合计": "total_amount", "合计": "total_amount", "total_amount": "total_amount",
    "费用类别": "category", "类别": "category", "category": "category",
    "备注": "remark", "remark": "remark",
}

DIRECTION_ALIASES = {
    "进项": "input", "收票": "input", "input": "input", "in": "input",
    "销项": "output", "开票": "output", "output": "output", "out": "output",
}
TYPE_ALIASES = {
    "专票": "special", "专用发票": "special", "special": "special",
    "普票": "normal", "普通发票": "normal", "normal": "normal",
    "数电票": "electronic", "电子发票": "electronic", "electronic": "electronic",
    "其他": "other", "other": "other",
}
CATEGORY_ALIASES = {
    "办公": "office", "办公费": "office", "office": "office",
    "差旅": "travel", "差旅费": "travel", "travel": "travel",
    "房租": "rent", "租金": "rent", "rent": "rent",
    "材料": "material", "采购": "material", "库存商品": "material", "material": "material",
    "招待": "entertain", "业务招待": "entertain", "entertain": "entertain",
    "水电": "utility", "物业": "utility", "utility": "utility",
    "通讯": "telecom", "网络": "telecom", "telecom": "telecom",
    "物流": "logistics", "运输": "logistics", "logistics": "logistics",
    "工资": "salary", "社保": "salary", "salary": "salary",
}


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """编码自动识别（DoD：GBK/UTF-8 容错，防表头乱码）。

    按 utf-8-sig → utf-8 → gb18030 → gbk 顺序尝试，返回 (文本, 编码名)。
    """
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def parse_table(raw: bytes, filename: str = "") -> list[dict]:
    """把上传的 xlsx / csv 解析成 dict 列表（自动识别编码与表头）。

    返回：[{字段名: 单元格值}, ...]；表头识别不了的行原样按列序取名 col0/col1...
    """
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        return _parse_xlsx(raw)
    return _parse_csv(raw)


def _parse_xlsx(raw: bytes) -> list[dict]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    return _rows_to_dicts([[c for c in r] for r in rows])


def _parse_csv(raw: bytes) -> list[dict]:
    text, _enc = decode_bytes(raw)
    # 自动嗅探分隔符
    first = text.splitlines()[0] if text.splitlines() else ""
    delim = "," if first.count(",") >= first.count("\t") else "\t"
    if first.count(";") > max(first.count(","), first.count("\t")):
        delim = ";"
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    return _rows_to_dicts([r for r in reader])


def _rows_to_dicts(rows: list[list]) -> list[dict]:
    if not rows:
        return []
    # 跳过前面的空行，找到第一个非空行当表头
    idx = 0
    while idx < len(rows) and not any(str(c or "").strip() for c in rows[idx]):
        idx += 1
    if idx >= len(rows):
        return []
    header = [str(c or "").strip() for c in rows[idx]]
    fields = [HEADER_ALIASES.get(h, h) for h in header]
    # 表头一个都没识别出来 → 认为无表头，按 col 序号命名
    if not any(f in HEADER_ALIASES.values() for f in fields):
        fields = [f"col{i}" for i in range(len(header))]
    out = []
    for r in rows[idx + 1:]:
        if not any(str(c or "").strip() for c in r):
            continue
        item = {}
        for i, f in enumerate(fields):
            item[f] = r[i] if i < len(r) else None
        out.append(item)
    return out


def _norm_direction(v) -> str:
    s = str(v or "").strip()
    return DIRECTION_ALIASES.get(s, s.lower() if s.lower() in ("input", "output") else "input")


def _norm_type(v) -> str:
    s = str(v or "").strip()
    return TYPE_ALIASES.get(s, s.lower() if s.lower() in
                            ("special", "normal", "electronic", "other") else "special")


def _norm_category(v):
    s = str(v or "").strip()
    if not s:
        return None
    return CATEGORY_ALIASES.get(s, s.lower() if s.lower() in CATEGORY_ALIASES.values() else "other")


def validate_rows(db: Session, book_id: int, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """逐行校验 → (合法行, 错误行)。错误行带 row 行号与错误说明（前端标红）。

    批内也查重（同批重复号码+日期）。
    """
    ok, errors = [], []
    seen: set[tuple] = set()
    for i, r in enumerate(rows, start=2):   # 第 1 行是表头
        try:
            no = str(r.get("invoice_no") or "").strip()
            if not no:
                raise BizError("invoice_no_required", "发票号码为空")
            idate = _parse_date(r.get("invoice_date"))
            direction = _norm_direction(r.get("direction"))
            if direction not in ("input", "output"):
                raise BizError("direction_invalid", f"方向必须是 进项/销项，当前「{r.get('direction')}」")
            goods_raw = r.get("goods_amount")
            if goods_raw in (None, ""):
                raise BizError("goods_required", "不含税金额为空")
            goods, tax, total = compute_amounts(
                goods=goods_raw, tax=r.get("tax_amount"),
                total=r.get("total_amount"), rate=r.get("tax_rate"))
            if total <= 0:
                raise BizError("amount_invalid", "价税合计必须大于 0")

            code = str(r["invoice_code"]).strip() if r.get("invoice_code") else None
            key = (code, no, idate)
            if key in seen:
                raise BizError("batch_duplicate", "本批次内重复")
            seen.add(key)
            if find_duplicate(db, book_id, code, no, idate):
                raise BizError("invoice_duplicate", "系统中已存在相同发票")

            ok.append({
                "direction": direction,
                "invoice_type": _norm_type(r.get("invoice_type")),
                "invoice_code": code, "invoice_no": no, "invoice_date": idate,
                "period": period_of(idate),
                "partner_name": (str(r["partner_name"]).strip() if r.get("partner_name") else None),
                "partner_tax_no": (str(r["partner_tax_no"]).strip() if r.get("partner_tax_no") else None),
                "goods_amount": goods, "tax_amount": tax, "total_amount": total,
                "tax_rate": _d(r.get("tax_rate")),
                "category": _norm_category(r.get("category")),
                "remark": (str(r["remark"]).strip() if r.get("remark") else None),
                "source": "excel",
            })
        except BizError as e:
            errors.append({"row": i, "code": e.code, "message": e.message,
                           "data": {k: _safe_str(v) for k, v in r.items()}})
        except Exception as e:      # 日期/数字解析异常等
            errors.append({"row": i, "code": "parse_error", "message": str(e)[:120],
                           "data": {k: _safe_str(v) for k, v in r.items()}})
    return ok, errors


def _safe_str(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def commit_rows(db: Session, book_id: int, rows: list[dict],
                user_id: int | None = None) -> int:
    """批量入库（已校验过的行）。返回新建条数。"""
    now = datetime.now()
    for r in rows:
        db.add(InvoiceBill(
            **r, state="registered", book_id=book_id,
            create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
        ))
    db.flush()
    return len(rows)


# ==================== 月末视图（7.6：申报底稿取数来源） ====================

def month_summary(db: Session, book_id: int, period: str) -> dict:
    """某期间进项/销项合计（增值税申报底稿的直接取数来源）。"""
    def agg(direction: str) -> dict:
        row = db.execute(
            select(func.count(InvoiceBill.id),
                   func.coalesce(func.sum(InvoiceBill.goods_amount), 0),
                   func.coalesce(func.sum(InvoiceBill.tax_amount), 0),
                   func.coalesce(func.sum(InvoiceBill.total_amount), 0))
            .where(InvoiceBill.book_id == book_id, InvoiceBill.active.is_(True),
                   InvoiceBill.period == period, InvoiceBill.direction == direction,
                   InvoiceBill.state != "voided")
        ).one()
        return {"count": int(row[0] or 0), "goods": str(_q(_d(row[1]))),
                "tax": str(_q(_d(row[2]))), "total": str(_q(_d(row[3])))}

    output, input_ = agg("output"), agg("input")
    vat = _q(_d(output["tax"]) - _d(input_["tax"]))   # 应纳税额 = 销项 - 进项（未扣留抵）
    return {"period": period, "output": output, "input": input_,
            "vat_payable": str(vat)}


# ==================== 序列化 ====================

def invoice_to_dict(inv: InvoiceBill) -> dict:
    return {
        "id": inv.id, "direction": inv.direction, "invoice_type": inv.invoice_type,
        "invoice_code": inv.invoice_code, "invoice_no": inv.invoice_no,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "period": inv.period,
        "partner_name": inv.partner_name, "partner_tax_no": inv.partner_tax_no,
        "partner_id": inv.partner_id,
        "goods_amount": str(_q(_d(inv.goods_amount))),
        "tax_amount": str(_q(_d(inv.tax_amount))),
        "total_amount": str(_q(_d(inv.total_amount))),
        "tax_rate": str(_d(inv.tax_rate)),
        "category": inv.category, "state": inv.state, "move_id": inv.move_id,
        "remark": inv.remark, "source": inv.source,
        "attachment_path": inv.attachment_path, "book_id": inv.book_id,
    }
