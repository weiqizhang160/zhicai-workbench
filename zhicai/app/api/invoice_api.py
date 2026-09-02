# -*- coding: utf-8 -*-
"""发票 API（M3，项目书 7.6）：CRUD / Excel 导入 / 月末视图 / 影像上传。"""
import io
import os
import time
from datetime import date


def now_ms() -> float:
    return time.time()

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.book_context import ALL_BOOKS, get_book_id
from ..core.db import get_db
from ..core.errors import BizError
from ..modules.base.models import ResUsers
from ..modules.invoice import service as inv_svc
from ..modules.invoice.models import InvoiceBill
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/inv", tags=["invoice"])

# 导入模板列（中文表头，与 HEADER_ALIASES 对应）
TEMPLATE_HEADER = ["方向", "票种", "发票代码", "发票号码", "开票日期", "对方名称",
                   "对方税号", "不含税金额", "税率", "费用类别", "备注"]
TEMPLATE_SAMPLE = ["进项", "专票", "011002100411", "00001234", "2026-09-01",
                   "深圳市XX供应商", "91440300XXXXXXXXXX", "1000.00", "0.13", "办公", ""]


def _require_book(request: Request) -> int:
    book_id = get_book_id(request)
    if book_id == ALL_BOOKS or not isinstance(book_id, int):
        raise BizError("book_required", "请先在右上角选择一个客户账套")
    return book_id


class InvoiceBody(BaseModel):
    direction: str = "input"
    invoice_type: str = "special"
    invoice_code: str | None = None
    invoice_no: str = ""
    invoice_date: str = ""
    partner_name: str | None = None
    partner_tax_no: str | None = None
    partner_id: int | None = None
    goods_amount: str | float | None = "0"
    tax_amount: str | float | None = None
    total_amount: str | float | None = None
    tax_rate: str | float | None = "0"
    category: str | None = None
    remark: str | None = None


@router.get("/bills")
def list_invoices(
    request: Request,
    direction: str | None = Query(None),
    period: str | None = Query(None),
    state: str | None = Query(None),
    category: str | None = Query(None),
    kw: str | None = Query(None),
    limit: int = Query(80, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: ResUsers = Depends(require_role("read")),
    db: Session = Depends(get_db),
):
    book_id = _require_book(request)
    q = select(InvoiceBill).where(InvoiceBill.book_id == book_id, InvoiceBill.active.is_(True))
    if direction:
        q = q.where(InvoiceBill.direction == direction)
    if period:
        q = q.where(InvoiceBill.period == period)
    if state:
        q = q.where(InvoiceBill.state == state)
    if category:
        q = q.where(InvoiceBill.category == category)
    if kw:
        like = f"%{kw.strip()}%"
        q = q.where(or_(InvoiceBill.invoice_no.ilike(like),
                        InvoiceBill.partner_name.ilike(like),
                        InvoiceBill.invoice_code.ilike(like)))
    rows = db.execute(
        q.order_by(InvoiceBill.invoice_date.desc(), InvoiceBill.id.desc())
        .limit(limit).offset(offset)).scalars().all()
    return {"invoices": [inv_svc.invoice_to_dict(r) for r in rows], "total": len(rows)}


@router.post("/bills")
def create_invoice(body: InvoiceBody, request: Request,
                   user: ResUsers = Depends(require_role("create")),
                   db: Session = Depends(get_db)):
    book_id = _require_book(request)
    inv = inv_svc.create_invoice(db, book_id, body.model_dump(), user.id)
    return {"ok": True, "invoice": inv_svc.invoice_to_dict(inv)}


@router.get("/bills/{inv_id}")
def get_invoice(inv_id: int, user: ResUsers = Depends(require_role("read")),
                db: Session = Depends(get_db)):
    inv = db.get(InvoiceBill, inv_id)
    if inv is None or not inv.active:
        raise BizError("not_found", "发票不存在")
    return {"invoice": inv_svc.invoice_to_dict(inv)}


@router.put("/bills/{inv_id}")
def update_invoice(inv_id: int, body: InvoiceBody,
                   user: ResUsers = Depends(require_role("write")),
                   db: Session = Depends(get_db)):
    inv = db.get(InvoiceBill, inv_id)
    if inv is None or not inv.active:
        raise BizError("not_found", "发票不存在")
    inv = inv_svc.update_invoice(db, inv, body.model_dump(), user.id)
    return {"ok": True, "invoice": inv_svc.invoice_to_dict(inv)}


@router.delete("/bills/{inv_id}")
def delete_invoice(inv_id: int, user: ResUsers = Depends(require_role("delete")),
                   db: Session = Depends(get_db)):
    inv = db.get(InvoiceBill, inv_id)
    if inv is None:
        raise BizError("not_found", "发票不存在")
    if inv.state == "entry_generated":
        raise BizError("invoice_locked", "已生成凭证的发票不能删除，请先删除对应凭证")
    inv.active = False
    db.flush()
    return {"ok": True}


# ==================== 导入（Excel / CSV） ====================

@router.get("/template")
def download_template(user: ResUsers = Depends(require_login)):
    """下载标准导入模板（CSV，带 BOM 防 Excel 中文乱码）。"""
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TEMPLATE_HEADER)
    w.writerow(TEMPLATE_SAMPLE)
    data = "\ufeff" + buf.getvalue()
    return StreamingResponse(
        io.BytesIO(data.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=invoice_template.csv"},
    )


@router.post("/import-preview")
async def import_preview(request: Request, file: UploadFile = File(...),
                         user: ResUsers = Depends(require_role("create")),
                         db: Session = Depends(get_db)):
    """上传文件 → 逐行校验 → 返回 (可导入行, 错误行)。不落库。"""
    book_id = _require_book(request)
    raw = await file.read()
    if not raw:
        raise BizError("empty_file", "文件内容为空")
    try:
        rows = inv_svc.parse_table(raw, file.filename or "")
    except BizError:
        raise
    except Exception as e:
        raise BizError("parse_failed", f"文件解析失败：{str(e)[:150]}")
    if not rows:
        raise BizError("empty_rows", "未解析到数据行，请检查表头是否符合模板")

    ok, errors = inv_svc.validate_rows(db, book_id, rows)
    # 预览只回传前 200 行，避免响应过大
    preview = [dict(r, invoice_date=r["invoice_date"].isoformat(),
                    goods_amount=str(r["goods_amount"]), tax_amount=str(r["tax_amount"]),
                    total_amount=str(r["total_amount"]), tax_rate=str(r["tax_rate"]))
               for r in ok[:200]]
    return {"total": len(rows), "valid": len(ok), "invalid": len(errors),
            "preview": preview, "errors": errors[:100]}


class CommitBody(BaseModel):
    rows: list[dict]


@router.post("/import-commit")
def import_commit(body: CommitBody, request: Request,
                  user: ResUsers = Depends(require_role("create")),
                  db: Session = Depends(get_db)):
    """确认入库（前端把 preview 里的行原样回传）。"""
    book_id = _require_book(request)
    # 重新校验一次（防止前端篡改/重复提交）
    ok, errors = inv_svc.validate_rows(db, book_id, body.rows)
    if errors:
        raise BizError("rows_invalid", f"有 {len(errors)} 行不合法，请修正后重新导入")
    if not ok:
        raise BizError("no_valid_rows", "没有可导入的有效行")
    n = inv_svc.commit_rows(db, book_id, ok, user.id)
    return {"ok": True, "imported": n}


# ==================== 月末视图（申报底稿取数来源） ====================

@router.get("/month-summary")
def month_summary(request: Request, period: str,
                  user: ResUsers = Depends(require_role("read")),
                  db: Session = Depends(get_db)):
    """某期间进项/销项合计（增值税申报底稿直接取数）。"""
    book_id = _require_book(request)
    return inv_svc.month_summary(db, book_id, period)


# ==================== 影像上传 ====================

@router.post("/bills/{inv_id}/attachment")
async def upload_attachment(inv_id: int, file: UploadFile = File(...),
                            user: ResUsers = Depends(require_role("write")),
                            db: Session = Depends(get_db)):
    """上传发票影像（拍照/扫描件），存 data/attachments/年/月/ 下。"""
    inv = db.get(InvoiceBill, inv_id)
    if inv is None or not inv.active:
        raise BizError("not_found", "发票不存在")
    raw = await file.read()
    if not raw:
        raise BizError("empty_file", "文件内容为空")
    if len(raw) > 10 * 1024 * 1024:
        raise BizError("file_too_large", "影像文件不能超过 10MB")

    today = date.today()
    rel_dir = f"attachments/{today.year}/{today.month:02d}"
    abs_dir = os.path.join("data", rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    fname = f"inv_{inv_id}_{int(now_ms() * 1000) % 100000}{ext}"
    with open(os.path.join(abs_dir, fname), "wb") as f:
        f.write(raw)
    inv.attachment_path = f"{rel_dir}/{fname}"
    db.flush()

    # M6 文档中心挂接：同步登记一条 doc_document（7.12 DoD：发票页上传 → 文档中心反查）
    from ..modules.documents import service as docs_service
    docs_service.create_doc(
        db, book_id=inv.book_id,
        name=f"{inv.invoice_no or '发票'} 影像",
        doc_type="invoice",
        tags="发票影像",
        doc_year=today.year,
        attachment_path=inv.attachment_path,
        file_size=len(raw),
        source_model="invoice_bill", source_id=inv_id,
        user_id=user.id,
    )
    db.flush()
    return {"ok": True, "path": inv.attachment_path}
