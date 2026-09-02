# -*- coding: utf-8 -*-
"""文档中心 API（M6，项目书 7.12）：上传 / 跨账套列表 / 在线预览 / 业务单据挂接。

- 上传：multipart 多文件（拖拽一次传多个），每个文件一条 doc_document；
- 列表：跨账套（客户/类型/标签/年份/关键字筛选），总览模式是核心场景；
- 预览：GET /{id}/file 按扩展名给 MIME，图片/PDF 直接内联展示；
- 挂接：上传时带 source_model/source_id（发票页/报关单页直传），
  GET /by-source/{model}/{id} 反查来源单据的全部文档（DoD）。
"""
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.errors import BizError
from ..modules.base.models import ResUsers
from ..modules.documents import service as docs
from ..modules.documents.views import DOC_TYPE_OPTIONS
from ..modules.res_partner.models import ResBook
from .deps import require_login, require_role

router = APIRouter(prefix="/api/v1/docs", tags=["documents"])

VALID_DOC_TYPES = {o["value"] for o in DOC_TYPE_OPTIONS}


def _valid_book(db: Session, book_id: int) -> ResBook:
    book = db.get(ResBook, book_id)
    if book is None or not book.active:
        raise BizError("not_found", "客户账套不存在")
    return book


# ==================== 上传（多文件） ====================

@router.post("/upload")
async def upload(files: list[UploadFile] = File(...),
                 book_id: int = Form(...),
                 doc_type: str = Form("other"),
                 tags: str | None = Form(None),
                 doc_year: int | None = Form(None),
                 name: str | None = Form(None),
                 source_model: str | None = Form(None),
                 source_id: int | None = Form(None),
                 remark: str | None = Form(None),
                 user: ResUsers = Depends(require_role("create")),
                 db: Session = Depends(get_db)):
    """拖拽/选择多文件上传，每个文件生成一条文档记录。"""
    if not files:
        raise BizError("no_files", "请选择要上传的文件")
    if len(files) > 20:
        raise BizError("too_many_files", "单次最多上传 20 个文件")
    _valid_book(db, book_id)
    if doc_type not in VALID_DOC_TYPES:
        raise BizError("bad_doc_type", f"未知文档类型：{doc_type}")

    created = []
    for i, f in enumerate(files):
        raw = await f.read()
        rel_path, size = docs.save_file(raw, f.filename or "")
        # 文档名：优先用户给的统一名（多文件时自动加序号），否则用原文件名
        if name:
            stem = name if len(files) == 1 else f"{name}({i + 1})"
        else:
            stem = Path(f.filename or rel_path).stem
        doc = docs.create_doc(
            db, book_id=book_id, name=stem, doc_type=doc_type, tags=tags,
            doc_year=doc_year, attachment_path=rel_path, file_size=size,
            source_model=source_model, source_id=source_id, remark=remark,
            user_id=user.id)
        created.append(docs.doc_to_dict(doc))
    db.commit()
    return {"ok": True, "count": len(created), "records": created}


# ==================== 列表 / 详情 ====================

@router.get("")
def list_documents(book_id: int | None = Query(None, description="指定客户则只看该客户"),
                   doc_type: str | None = Query(None),
                   tag: str | None = Query(None),
                   year: int | None = Query(None),
                   search: str | None = Query(None),
                   limit: int = Query(80, ge=1, le=500),
                   offset: int = Query(0, ge=0),
                   user: ResUsers = Depends(require_login),
                   db: Session = Depends(get_db)):
    """跨账套文档列表（7.12 DoD：客户/类型/标签/年份筛选）。"""
    total, records = docs.list_docs(
        db, book_id=book_id, doc_type=doc_type, tag=tag, doc_year=year,
        search=search, limit=limit, offset=offset)
    return {"total": total, "records": records}


@router.get("/stats")
def stats(user: ResUsers = Depends(require_login),
          db: Session = Depends(get_db)):
    return docs.doc_stats(db)


@router.get("/by-source/{source_model}/{source_id}")
def by_source(source_model: str, source_id: int,
              user: ResUsers = Depends(require_login),
              db: Session = Depends(get_db)):
    """反查业务单据（发票/报关单/合同…）挂接的全部文档。"""
    return {"records": docs.find_by_source(db, source_model, source_id)}


@router.get("/{doc_id}")
def get_document(doc_id: int,
                 user: ResUsers = Depends(require_login),
                 db: Session = Depends(get_db)):
    doc = docs.get_doc(db, doc_id)
    return {"record": docs.doc_to_dict(doc)}


class DocUpdateBody(BaseModel):
    values: dict


@router.put("/{doc_id}")
def update_document(doc_id: int, body: DocUpdateBody,
                    user: ResUsers = Depends(require_role("write")),
                    db: Session = Depends(get_db)):
    doc = docs.get_doc(db, doc_id)
    docs.update_doc(db, doc, body.values or {}, user_id=user.id)
    db.commit()
    return {"ok": True, "record": docs.doc_to_dict(doc)}


@router.delete("/{doc_id}")
def delete_document(doc_id: int,
                    user: ResUsers = Depends(require_role("delete")),
                    db: Session = Depends(get_db)):
    doc = docs.get_doc(db, doc_id)
    doc.active = False
    doc.write_uid = user.id
    doc.write_date = datetime.now()
    db.commit()
    return {"ok": True}


# ==================== 文件预览 / 下载 ====================

@router.get("/{doc_id}/file")
def doc_file(doc_id: int,
             download: bool = Query(False, description="true=下载，默认在线预览"),
             user: ResUsers = Depends(require_login),
             db: Session = Depends(get_db)):
    """文件流：图片/PDF 内联预览，其他类型按附件下载。"""
    doc = docs.get_doc(db, doc_id)
    p = docs.resolve_path(doc.attachment_path)
    if p is None or not p.is_file():
        raise BizError("file_missing", "文件不存在（可能已被移动或删除）")
    media = docs.mime_of(p)
    fname = doc.name + p.suffix.lower()
    disp = "attachment" if download else "inline"
    return FileResponse(
        p, media_type=media,
        headers={"Content-Disposition": f'{disp}; filename*=UTF-8\'\'{quote(fname)}'})
