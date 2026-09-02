# -*- coding: utf-8 -*-
"""foreign_trade 业务逻辑（项目书 7.10）：报关单 CRUD / CSV 导入 / 收汇差额 / 退税流转 / 平台链接。"""
import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ..base.models import IrConfig
from ..res_partner.models import ResBook
from .models import FtCustomsDecl, FtCustomsLine, FtExportRefund, FxFxReceipt

ZERO = Decimal("0.00")

PLATFORM_LINKS_KEY = "ft.platform_links"
PLATFORM_NOTES_KEY = "ft.platform_notes"

DEFAULT_PLATFORM_LINKS = {
    "single_window": {"name": "中国国际贸易单一窗口",
                      "url": "https://www.singlewindow.cn/"},
    "e_port": {"name": "中国电子口岸",
               "url": "https://www.chinaport.gov.cn/"},
    "safe": {"name": "国家外汇管理局数字外管",
             "url": "https://asone.safesvc.gov.cn/"},
    "etax_refund": {"name": "电子税务局（出口退税模块）",
                    "url": "https://etax.chinatax.gov.cn/"},
}


def _dec(v) -> Decimal:
    if v is None or v == "":
        return ZERO
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return ZERO


def _d(v) -> str:
    return str(_dec(v).quantize(Decimal("0.01")))


# ==================== 报关单 ====================

def lines_of(db: Session, decl_id: int) -> list[FtCustomsLine]:
    return db.execute(
        select(FtCustomsLine)
        .where(FtCustomsLine.decl_id == decl_id, FtCustomsLine.active.is_(True))
        .order_by(FtCustomsLine.id)
    ).scalars().all()


def create_decl(db: Session, *, book_id: int, decl_no: str, export_date: date,
                trade_mode: str = "FOB", currency: str = "USD", fx_rate="1",
                usd_amount="0", customer_abroad: str | None = None,
                goods_count: int = 0, remark: str | None = None,
                lines: list[dict] | None = None, user_id: int | None = None) -> FtCustomsDecl:
    if not (decl_no or "").strip():
        raise BizError("decl_no_required", "报关单号不能为空")
    dup = db.execute(
        select(FtCustomsDecl.id).where(
            FtCustomsDecl.book_id == book_id, FtCustomsDecl.decl_no == decl_no.strip(),
            FtCustomsDecl.active.is_(True))
    ).scalar_one_or_none()
    if dup is not None:
        raise BizError("decl_no_dup", f"报关单号 {decl_no} 已存在")
    if trade_mode not in ("FOB", "CIF", "CFR"):
        raise BizError("trade_mode_invalid", "成交方式必须是 FOB/CIF/CFR 之一")

    rate = _dec(fx_rate)
    amount = _dec(usd_amount)
    now = datetime.now()
    decl = FtCustomsDecl(
        book_id=book_id, decl_no=decl_no.strip(), export_date=export_date,
        trade_mode=trade_mode, currency=(currency or "USD").strip(), fx_rate=rate,
        usd_amount=amount, cny_total=(amount * rate).quantize(Decimal("0.01")),
        customer_abroad=customer_abroad or None, goods_count=goods_count or 0,
        remark=remark or None,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
    )
    db.add(decl)
    db.flush()
    for ln in (lines or []):
        add_line(db, decl, ln, user_id)
    recalc_decl_totals(db, decl)
    db.flush()
    return decl


def add_line(db: Session, decl: FtCustomsDecl, data: dict,
             user_id: int | None = None) -> FtCustomsLine:
    if not (data.get("goods_name") or "").strip():
        raise BizError("goods_name_required", "商品行品名不能为空")
    now = datetime.now()
    line = FtCustomsLine(
        decl_id=decl.id, book_id=decl.book_id,
        hs_code=(data.get("hs_code") or "").strip() or None,
        goods_name=data["goods_name"].strip(),
        qty=_dec(data.get("qty")), unit=(data.get("unit") or None),
        unit_price=_dec(data.get("unit_price")), amount=_dec(data.get("amount")),
        remark=data.get("remark") or None,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
    )
    db.add(line)
    db.flush()
    return line


def recalc_decl_totals(db: Session, decl: FtCustomsDecl) -> None:
    """按商品行重算外币金额与人民币总额（行金额优先；无行时保留手工金额）。"""
    lines = lines_of(db, decl.id)
    if lines:
        decl.usd_amount = sum((ln.amount for ln in lines), ZERO).quantize(Decimal("0.01"))
    decl.cny_total = (decl.usd_amount * _dec(decl.fx_rate)).quantize(Decimal("0.01"))
    db.flush()


def decl_to_dict(db: Session, d: FtCustomsDecl, with_lines: bool = False) -> dict:
    book = db.get(ResBook, d.book_id)
    received = received_amount_of(db, d.id)
    out = {
        "id": d.id, "book_id": d.book_id,
        "book_name": book.short_name if book else None,
        "decl_no": d.decl_no,
        "export_date": d.export_date.isoformat() if d.export_date else None,
        "trade_mode": d.trade_mode, "currency": d.currency,
        "fx_rate": str(d.fx_rate or 1),
        "usd_amount": _d(d.usd_amount), "cny_total": _d(d.cny_total),
        "customer_abroad": d.customer_abroad, "goods_count": d.goods_count,
        "remark": d.remark,
        "received_amount": _d(received),
        "unreceived": _d(_dec(d.usd_amount) - received),
    }
    if with_lines:
        out["lines"] = [line_to_dict(ln) for ln in lines_of(db, d.id)]
    return out


def line_to_dict(ln: FtCustomsLine) -> dict:
    return {
        "id": ln.id, "decl_id": ln.decl_id, "hs_code": ln.hs_code,
        "goods_name": ln.goods_name, "qty": str(ln.qty or 0), "unit": ln.unit,
        "unit_price": str(ln.unit_price or 0), "amount": _d(ln.amount),
        "remark": ln.remark,
    }


# ==================== 单一窗口 CSV 导入 ====================

# 列名别名映射（单一窗口导出的报表表头各版本不一致，宽松匹配）
_DECL_HEADER_ALIASES = {
    "decl_no": ["报关单号", "海关编号", "统一编号", "单号"],
    "export_date": ["出口日期", "申报日期", "日期"],
    "trade_mode": ["成交方式", "贸易方式"],
    "currency": ["币制", "币种", "结算货币"],
    "fx_rate": ["汇率"],
    "usd_amount": ["总价", "总金额", "合计金额", "申报金额"],
    "customer_abroad": ["境外客户", "客户名称", "买方", "境外收发货人"],
    "goods_count": ["件数", "包装件数"],
    "hs_code": ["商品编码", "海关编码", "HS编码"],
    "goods_name": ["品名", "商品名称", "货物名称"],
    "qty": ["数量", "申报数量", "成交数量"],
    "unit": ["单位", "计量单位"],
    "unit_price": ["单价", "申报单价"],
    "amount": ["金额", "申报金额", "成交金额"],
}


def _match_headers(header: list[str]) -> dict[str, int]:
    """把 CSV 表头映射到字段名（宽松：包含匹配 + 去空白）。"""
    result = {}
    for idx, raw in enumerate(header):
        cell = (raw or "").replace(" ", "").replace("\u3000", "")
        if not cell:
            continue
        for field, aliases in _DECL_HEADER_ALIASES.items():
            if field in result:
                continue
            if any(a.replace(" ", "") in cell for a in aliases):
                result[field] = idx
    return result


def import_decl_rows(db: Session, book_id: int, rows: list[list[str]],
                     user_id: int | None = None) -> dict:
    """导入单一窗口导出的报关明细 CSV（rows 已解析为二维数组，首行为表头）。

    幂等：报关单号已存在则跳过整行。
    """
    if not rows:
        raise BizError("empty_rows", "没有可导入的行")
    header_map = _match_headers(rows[0])
    if "decl_no" not in header_map:
        raise BizError("header_not_recognized",
                       "未识别到「报关单号」列，请确认导出的是单一窗口报关明细")

    def cell(row: list[str], field: str) -> str:
        idx = header_map.get(field)
        if idx is None or idx >= len(row):
            return ""
        return (row[idx] or "").strip()

    created, skipped, errors = 0, 0, []
    for ridx, row in enumerate(rows[1:], start=2):
        if not any((c or "").strip() for c in row):
            continue
        decl_no = cell(row, "decl_no")
        if not decl_no:
            errors.append({"row": ridx, "message": "报关单号为空"})
            continue
        exists = db.execute(
            select(FtCustomsDecl.id).where(
                FtCustomsDecl.book_id == book_id, FtCustomsDecl.decl_no == decl_no,
                FtCustomsDecl.active.is_(True))
        ).scalar_one_or_none()
        if exists is not None:
            skipped += 1
            continue

        # 解析日期（支持 YYYY-MM-DD / YYYY/M/D）
        raw_date = cell(row, "export_date")[:10].replace("/", "-")
        try:
            parts = [int(p) for p in raw_date.split("-")]
            export_date = date(parts[0], parts[1], parts[2])
        except Exception:
            export_date = date.today()

        try:
            line_data = None
            if "goods_name" in header_map and cell(row, "goods_name"):
                line_data = {
                    "hs_code": cell(row, "hs_code"),
                    "goods_name": cell(row, "goods_name"),
                    "qty": cell(row, "qty") or 0,
                    "unit": cell(row, "unit"),
                    "unit_price": cell(row, "unit_price") or 0,
                    "amount": cell(row, "amount") or cell(row, "usd_amount") or 0,
                }
            create_decl(
                db, book_id=book_id, decl_no=decl_no, export_date=export_date,
                trade_mode=cell(row, "trade_mode") or "FOB",
                currency=cell(row, "currency") or "USD",
                fx_rate=cell(row, "fx_rate") or "1",
                usd_amount=cell(row, "usd_amount") or "0",
                customer_abroad=cell(row, "customer_abroad") or None,
                goods_count=int(_dec(cell(row, "goods_count"))),
                lines=[line_data] if line_data else None,
                user_id=user_id,
            )
            created += 1
        except BizError as e:
            if e.code == "decl_no_dup":
                skipped += 1
            else:
                errors.append({"row": ridx, "message": e.message})
    db.flush()
    return {"created": created, "skipped": skipped, "errors": errors}


# ==================== 收汇 ====================

def received_amount_of(db: Session, decl_id: int) -> Decimal:
    """报关单已收汇金额（收汇/待核查/结汇均计入，扣银行手续费前的外币口径）。"""
    rows = db.execute(
        select(FxFxReceipt.amount).where(
            FxFxReceipt.decl_id == decl_id, FxFxReceipt.active.is_(True))
    ).all()
    return sum((r[0] for r in rows), ZERO).quantize(Decimal("0.01"))


def create_receipt(db: Session, *, book_id: int, decl_id: int | None,
                   receipt_date: date, currency: str = "USD", amount="0",
                   fx_rate="1", kind: str = "receipt", bank_fee="0",
                   remark: str | None = None, user_id: int | None = None) -> FxFxReceipt:
    if kind not in ("receipt", "verification", "settlement"):
        raise BizError("kind_invalid", "类型必须是 receipt/verification/settlement 之一")
    if decl_id is not None:
        decl = db.get(FtCustomsDecl, decl_id)
        if decl is None or not decl.active:
            raise BizError("decl_not_found", "报关单不存在")
    amt, rate = _dec(amount), _dec(fx_rate)
    if amt <= 0:
        raise BizError("amount_invalid", "收汇金额必须大于 0")
    now = datetime.now()
    row = FxFxReceipt(
        book_id=book_id, decl_id=decl_id, receipt_date=receipt_date,
        currency=(currency or "USD").strip(), amount=amt, fx_rate=rate,
        cny_amount=(amt * rate).quantize(Decimal("0.01")), kind=kind,
        bank_fee=_dec(bank_fee), remark=remark or None,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
    )
    db.add(row)
    db.flush()
    return row


def receipt_to_dict(db: Session, r: FxFxReceipt) -> dict:
    book = db.get(ResBook, r.book_id)
    decl = db.get(FtCustomsDecl, r.decl_id) if r.decl_id else None
    return {
        "id": r.id, "book_id": r.book_id,
        "book_name": book.short_name if book else None,
        "decl_id": r.decl_id, "decl_no": decl.decl_no if decl else None,
        "receipt_date": r.receipt_date.isoformat() if r.receipt_date else None,
        "currency": r.currency, "amount": _d(r.amount),
        "fx_rate": str(r.fx_rate or 1), "cny_amount": _d(r.cny_amount),
        "kind": r.kind, "bank_fee": _d(r.bank_fee), "remark": r.remark,
    }


# ==================== 出口退税 ====================

REFUND_FLOW = ["collecting", "submitted", "approved", "received"]


def create_refund(db: Session, *, book_id: int, decl_id: int, period: str,
                   kind: str = "免抵退", status: str = "collecting", refund_amount="0",
                   received_date: date | None = None, remark: str | None = None,
                   user_id: int | None = None) -> FtExportRefund:
    decl = db.get(FtCustomsDecl, decl_id)
    if decl is None or not decl.active:
        raise BizError("decl_not_found", "报关单不存在")
    if status not in REFUND_FLOW:
        raise BizError("status_invalid", f"状态必须是 {'/'.join(REFUND_FLOW)} 之一")
    if kind not in ("免抵退", "免退"):
        raise BizError("kind_invalid", "退税方式必须是 免抵退/免退 之一")
    now = datetime.now()
    row = FtExportRefund(
        book_id=book_id, decl_id=decl_id, period=period, kind=kind, status=status,
        refund_amount=_dec(refund_amount), received_date=received_date, remark=remark or None,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now, active=True,
    )
    db.add(row)
    db.flush()
    return row


def set_refund_status(db: Session, refund_id: int, status: str,
                      received_date: date | None = None) -> FtExportRefund:
    row = db.get(FtExportRefund, refund_id)
    if row is None or not row.active:
        raise BizError("not_found", "退税记录不存在")
    if status not in REFUND_FLOW:
        raise BizError("status_invalid", f"状态必须是 {'/'.join(REFUND_FLOW)} 之一")
    row.status = status
    if status == "received":
        row.received_date = received_date or date.today()
    db.flush()
    return row


def refund_to_dict(db: Session, r: FtExportRefund) -> dict:
    book = db.get(ResBook, r.book_id)
    decl = db.get(FtCustomsDecl, r.decl_id)
    return {
        "id": r.id, "book_id": r.book_id,
        "book_name": book.short_name if book else None,
        "decl_id": r.decl_id, "decl_no": decl.decl_no if decl else None,
        "period": r.period, "kind": r.kind, "status": r.status,
        "refund_amount": _d(r.refund_amount),
        "received_date": r.received_date.isoformat() if r.received_date else None,
        "remark": r.remark,
    }


# ==================== 平台链接中心 ====================

def ensure_platform_configs(db: Session) -> None:
    for key, default in ((PLATFORM_LINKS_KEY, DEFAULT_PLATFORM_LINKS),
                         (PLATFORM_NOTES_KEY, "")):
        row = db.execute(select(IrConfig).where(IrConfig.key == key)).scalar_one_or_none()
        if row is None:
            db.add(IrConfig(key=key, value=json.dumps(default, ensure_ascii=False)))
    db.flush()


def get_platform(db: Session) -> dict:
    ensure_platform_configs(db)
    links_row = db.execute(select(IrConfig).where(IrConfig.key == PLATFORM_LINKS_KEY)
                           ).scalar_one()
    notes_row = db.execute(select(IrConfig).where(IrConfig.key == PLATFORM_NOTES_KEY)
                           ).scalar_one()
    try:
        links = json.loads(links_row.value or "{}")
    except (ValueError, TypeError):
        links = {}
    return {"links": links, "notes": (notes_row.value or "").strip('"')}


def save_platform_notes(db: Session, notes: str) -> None:
    row = db.execute(select(IrConfig).where(IrConfig.key == PLATFORM_NOTES_KEY)
                     ).scalar_one()
    if row is None:
        db.add(IrConfig(key=PLATFORM_NOTES_KEY, value=notes))
    else:
        row.value = notes
    db.flush()


# ==================== 外贸汇总 ====================

def ft_summary(db: Session) -> dict:
    """外贸总览（仪表盘可扩展用）：报关总额 / 已收 / 未收 / 退税在途。"""
    decls = db.execute(select(FtCustomsDecl).where(FtCustomsDecl.active.is_(True))
                       ).scalars().all()
    total_cny = sum((_dec(d.cny_total) for d in decls), ZERO)
    total_received = ZERO
    for d in decls:
        received_amount_of(db, d.id)
    receipts = db.execute(select(FxFxReceipt).where(FxFxReceipt.active.is_(True))).scalars().all()
    total_received_cny = sum((_dec(r.cny_amount) for r in receipts), ZERO)
    pending_refund = db.execute(
        select(FtExportRefund).where(
            FtExportRefund.active.is_(True),
            FtExportRefund.status.in_(["collecting", "submitted", "approved"]))
    ).scalars().all()
    return {
        "decl_count": len(decls),
        "total_cny": _d(total_cny),
        "received_cny": _d(total_received_cny),
        "unreceived_cny": _d(total_cny - total_received_cny),
        "refund_pending_count": len(pending_refund),
        "refund_pending_amount": _d(sum((_dec(r.refund_amount) for r in pending_refund), ZERO)),
    }
