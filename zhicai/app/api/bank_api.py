# -*- coding: utf-8 -*-
"""银行流水 API（M3，项目书 7.8）：导入（编码容错）/ 对账工作台 / 月度汇总。"""
import csv
import io

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.book_context import ALL_BOOKS, get_book_id
from ..core.db import get_db
from ..core.errors import BizError
from ..modules.auto_entry import engine
from ..modules.bank import service as bank_svc
from ..modules.bank.models import BankStatement, BankStatementLine
from ..modules.base.models import ResUsers
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/bank", tags=["bank"])

TEMPLATE_HEADER = ["交易日期", "流水号", "对方户名", "摘要", "收入金额", "支出金额", "余额"]
TEMPLATE_SAMPLE = ["2026-09-01", "20260901001", "深圳市XX公司", "货款", "10000.00", "", "51000.00"]


def _require_book(request: Request) -> int:
    book_id = get_book_id(request)
    if book_id == ALL_BOOKS or not isinstance(book_id, int):
        raise BizError("book_required", "请先在右上角选择一个客户账套")
    return book_id


# ==================== 流水查询 ====================

@router.get("/lines")
def list_lines(request: Request, period: str | None = Query(None),
               state: str | None = Query(None), kw: str | None = Query(None),
               statement_id: int | None = Query(None),
               limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
               user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    book_id = _require_book(request)
    q = select(BankStatementLine).where(
        BankStatementLine.book_id == book_id, BankStatementLine.active.is_(True))
    if state:
        q = q.where(BankStatementLine.state == state)
    if statement_id:
        q = q.where(BankStatementLine.statement_id == statement_id)
    if period:
        q = q.where(BankStatementLine.trade_date >= _pstart(period),
                    BankStatementLine.trade_date <= _pend(period))
    if kw:
        like = f"%{kw.strip()}%"
        q = q.where(or_(BankStatementLine.summary.ilike(like),
                        BankStatementLine.counterpart_name.ilike(like),
                        BankStatementLine.trade_no.ilike(like)))
    rows = db.execute(
        # 未对账优先，便于对账工作台逐条处理
        q.order_by(BankStatementLine.state, BankStatementLine.trade_date.desc(),
                   BankStatementLine.id.desc()).limit(limit).offset(offset)).scalars().all()
    return {"lines": [bank_svc.line_to_dict(r) for r in rows], "total": len(rows)}


def _pstart(period: str):
    from datetime import date
    return date(int(period[:4]), int(period[5:7]), 1)


def _pend(period: str):
    from datetime import date, timedelta
    y, m = int(period[:4]), int(period[5:7])
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - timedelta(days=1)


@router.get("/statements")
def list_statements(request: Request, user: ResUsers = Depends(require_login),
                    db: Session = Depends(get_db)):
    book_id = _require_book(request)
    rows = db.execute(
        select(BankStatement).where(BankStatement.book_id == book_id,
                                    BankStatement.active.is_(True))
        .order_by(BankStatement.id.desc())).scalars().all()
    return {"statements": [{
        "id": s.id, "period": s.period, "bank_alias": s.bank_alias,
        "account_no": s.account_no, "line_count": s.line_count,
        "total_debit": str(s.total_debit), "total_credit": str(s.total_credit),
        "imported_at": s.imported_at.isoformat(sep=" ") if s.imported_at else None,
    } for s in rows]}


# ==================== 导入 ====================

@router.get("/template")
def download_template(user: ResUsers = Depends(require_login)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TEMPLATE_HEADER)
    w.writerow(TEMPLATE_SAMPLE)
    data = "\ufeff" + buf.getvalue()
    return StreamingResponse(
        io.BytesIO(data.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=bank_template.csv"})


@router.post("/import-preview")
async def import_preview(request: Request, file: UploadFile = File(...),
                         bank_alias: str | None = Query(None),
                         account_no: str | None = Query(None),
                         user: ResUsers = Depends(require_role("create")),
                         db: Session = Depends(get_db)):
    """上传对账单 → 解析（自动识别编码）→ 返回预览与错误行。不落库。"""
    book_id = _require_book(request)
    raw = await file.read()
    if not raw:
        raise BizError("empty_file", "文件内容为空")
    try:
        ok, errors, enc = bank_svc.parse_bank_file(db, raw, file.filename or "")
    except BizError:
        raise
    except Exception as e:
        raise BizError("parse_failed", f"文件解析失败：{str(e)[:150]}")
    if not ok:
        raise BizError("no_valid_rows",
                       f"未解析到有效流水行（识别编码：{enc}）。请检查表头是否符合模板，"
                       f"或在「参数配置」维护 bank.import.field_map")

    preview = [dict(r, trade_date=r["trade_date"].isoformat(),
                    debit=str(r["debit"]), credit=str(r["credit"]),
                    balance=(str(r["balance"]) if r["balance"] is not None else None))
               for r in ok[:200]]
    return {"valid": len(ok), "invalid": len(errors), "encoding": enc,
            "preview": preview, "errors": errors[:100]}


class BankCommitBody(BaseModel):
    rows: list[dict]
    bank_alias: str | None = None
    account_no: str | None = None


@router.post("/import-commit")
def import_commit(body: BankCommitBody, request: Request,
                  user: ResUsers = Depends(require_role("create")),
                  db: Session = Depends(get_db)):
    from datetime import date as _date
    book_id = _require_book(request)
    rows = []
    for r in body.rows:
        d = _date.fromisoformat(str(r["trade_date"])[:10])
        rows.append({
            "trade_date": d, "period": f"{d.year:04d}-{d.month:02d}",
            "trade_no": r.get("trade_no"), "counterpart_name": r.get("counterpart_name"),
            "summary": r.get("summary"),
            "debit": __import__("decimal").Decimal(str(r.get("debit") or 0)),
            "credit": __import__("decimal").Decimal(str(r.get("credit") or 0)),
            "balance": (__import__("decimal").Decimal(str(r["balance"]))
                        if r.get("balance") else None),
        })
    if not rows:
        raise BizError("no_rows", "没有可导入的流水行")
    stmt = bank_svc.import_statement(db, book_id, rows, bank_alias=body.bank_alias,
                                     account_no=body.account_no, user_id=user.id)
    return {"ok": True, "statement_id": stmt.id, "imported": len(rows)}


# ==================== 对账 ====================

@router.get("/lines/{line_id}/preview")
def preview_line(line_id: int, request: Request,
                 user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    """单条流水的凭证预览（命中规则自动带出分录）。"""
    book_id = _require_book(request)
    ln = db.get(BankStatementLine, line_id)
    if ln is None or not ln.active:
        raise BizError("not_found", "流水不存在")
    return {"preview": engine.preview_for_source(db, book_id, "bank_statement_line", ln),
            "line": bank_svc.line_to_dict(ln)}


class GenBody(BaseModel):
    rule_id: int | None = None
    lines: list[dict] | None = None


@router.post("/lines/{line_id}/generate-move")
def generate_move(line_id: int, body: GenBody | None = None, request: Request = None,
                  user: ResUsers = Depends(require_role("create")),
                  db: Session = Depends(get_db)):
    """生成凭证并把流水标记为已对账（DoD：状态联动）。"""
    book_id = _require_book(request)
    res = engine.execute_one(db, book_id, "bank_statement_line", line_id,
                             rule_id=body.rule_id if body else None,
                             override_lines=body.lines if body else None,
                             user_id=user.id)
    if not res.get("ok"):
        raise BizError(res.get("code") or "generate_failed",
                       res.get("message") or "生成凭证失败")
    return {"ok": True, **res}


@router.get("/month-summary")
def month_summary(request: Request, period: str,
                  user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    """期初 + 收入 - 支出 = 期末（与银行对账单核对）。"""
    book_id = _require_book(request)
    return bank_svc.month_summary(db, book_id, period)
