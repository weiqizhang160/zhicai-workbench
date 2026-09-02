# -*- coding: utf-8 -*-
"""业务动作 API（项目书 5.1 原则 3：状态流转与业务动作走显式端点）。"""
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.book_context import get_book_id
from ..core.db import get_db
from ..core.errors import BizError
from ..modules.account.service import book_account_count
from ..modules.base.models import ResUsers
from ..modules.res_partner import service as partner_service
from ..modules.res_partner.models import ResBook
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/biz", tags=["biz"])

BOOK_COOKIE = "zhicai_book"


# ---------- 账套切换器 ----------
@router.get("/books")
def list_books(user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    """顶栏切换器数据源：全部服务中/暂停的账套（terminated 隐藏，项目书 7.3）。"""
    rows = db.execute(
        select(ResBook)
        .where(ResBook.active.is_(True), ResBook.charge_status != "terminated")
        .order_by(ResBook.code)
    ).scalars().all()
    return {"books": [
        {"id": b.id, "code": b.code, "short_name": b.short_name,
         "charge_status": b.charge_status, "is_foreign_trade": b.is_foreign_trade}
        for b in rows
    ]}


@router.put("/books/{book_id}/switch")
def switch_book(book_id: int, response: Response,
                user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    """切换当前账套：写入 cookie（前端刷新数据即自动切账套）。"""
    if book_id != 0:
        book = db.get(ResBook, book_id)
        if book is None or not book.active:
            raise BizError("not_found", "账套不存在")
        if book.charge_status == "terminated":
            raise BizError("book_terminated", "该客户服务已终止，不能切换")
        response.set_cookie(BOOK_COOKIE, str(book_id), httponly=True, samesite="lax", path="/")
        return {"ok": True, "book": {"id": book.id, "short_name": book.short_name}}
    response.delete_cookie(BOOK_COOKIE, path="/")
    return {"ok": True, "book": None}


# ---------- 新建客户向导（项目书 7.3） ----------
class CreateBookBody(BaseModel):
    name: str
    short_name: str = ""
    credit_no: str = ""
    taxpayer_type: str = "small"
    accounting_standard: str = "small"
    is_foreign_trade: bool = False
    industry: str = ""
    legal_person: str = ""
    phone: str = ""
    address: str = ""
    bookkeeping_start: str | None = None
    remark: str = ""


@router.post("/books")
def create_book(body: CreateBookBody, user: ResUsers = Depends(require_role("create")),
                db: Session = Depends(get_db)):
    """新建客户账套：基本信息 + 科目表 + 账簿 + 编号器（一个事务）。"""
    book = partner_service.create_book(db, body.model_dump(), user.id)
    return {
        "ok": True,
        "book": {"id": book.id, "code": book.code, "name": book.name,
                 "short_name": book.short_name},
        "account_count": book_account_count(db, book.id),
    }


# ---------- 全局搜索（项目书 7.1：客户 + 科目；M2 扩展凭证号/发票号） ----------
@router.get("/search")
def global_search(q: str = Query(..., min_length=1), request: Request = None,
                  user: ResUsers = Depends(require_login), db: Session = Depends(get_db)):
    kw = f"%{q.strip()}%"
    results = []
    # 客户账套（跨账套搜索）
    books = db.execute(
        select(ResBook).where(
            ResBook.active.is_(True),
            or_(ResBook.short_name.ilike(kw), ResBook.name.ilike(kw),
                ResBook.code.ilike(kw), ResBook.credit_no.ilike(kw)),
        ).limit(10)
    ).scalars().all()
    for b in books:
        results.append({"type": "book", "id": b.id, "title": b.short_name,
                        "subtitle": f"{b.code} · {b.name}", "route": f"/form/res_book/{b.id}"})
    # 会计科目（仅当前账套）
    if request is not None:
        book_id = get_book_id(request)
        if isinstance(book_id, int):
            from ..modules.account.models import AccountAccount
            accounts = db.execute(
                select(AccountAccount).where(
                    AccountAccount.active.is_(True),
                    AccountAccount.book_id == book_id,
                    or_(AccountAccount.name.ilike(kw), AccountAccount.code.ilike(kw)),
                ).limit(10)
            ).scalars().all()
            for a in accounts:
                results.append({"type": "account", "id": a.id, "title": f"{a.code} {a.name}",
                                "subtitle": "会计科目", "route": f"/list/account_account"})
    return {"results": results[:20]}
