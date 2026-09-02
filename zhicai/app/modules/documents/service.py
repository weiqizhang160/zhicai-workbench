# -*- coding: utf-8 -*-
"""documents 模块业务逻辑：文件保存 / 跨账套查询 / 来源反查（项目书 7.12）。"""
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.orm import Session

from ...core.config import CONFIG
from ...core.errors import BizError
from .models import DocDocument

# 附件根目录（config.yaml 可改，默认 data/attachments/）
ATTACH_ROOT = Path(CONFIG.attachments_dir)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB（与发票影像口径一致）

# 允许的扩展名（白名单外的拒绝，防上传可执行文件）
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
                ".pdf", ".xlsx", ".xls", ".csv", ".docx", ".doc", ".txt", ".zip"}

# 在线预览支持的类型（前端 <img> / <iframe>）
PREVIEW_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".pdf": "application/pdf",
}

TAG_SANITIZE_RE = re.compile(r"[，,\s]+")


def save_file(raw: bytes, filename: str) -> tuple[str, int]:
    """把上传内容存到 attachments/年/月/ 下，返回 (相对路径, 大小)。

    相对路径形如 attachments/2026/09/doc_ab12cd.pdf —— 与发票影像同口径。
    """
    if not raw:
        raise BizError("empty_file", "文件内容为空")
    if len(raw) > MAX_FILE_SIZE:
        raise BizError("file_too_large", "文件不能超过 10MB")
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise BizError("bad_ext", f"不支持的文件类型：{ext or '(无扩展名)'}，"
                                  f"仅支持图片 / PDF / Office 文档 / zip")

    now = datetime.now()
    rel_dir = f"attachments/{now.year}/{now.month:02d}"
    abs_dir = ATTACH_ROOT / f"{now.year}/{now.month:02d}"
    abs_dir.mkdir(parents=True, exist_ok=True)
    fname = f"doc_{now.strftime('%H%M%S')}_{secrets.token_hex(3)}{ext}"
    with open(abs_dir / fname, "wb") as f:
        f.write(raw)
    return f"{rel_dir}/{fname}", len(raw)


def resolve_path(rel: str | None) -> Path | None:
    """把表里的相对路径解析成绝对路径（防目录穿越）。"""
    if not rel:
        return None
    rel = rel.replace("\\", "/")
    if rel.startswith("attachments/"):
        rel = rel[len("attachments/"):]
    root = ATTACH_ROOT.resolve()
    p = (ATTACH_ROOT / rel).resolve()
    if p != root and root not in p.parents:
        raise BizError("bad_path", "非法文件路径")
    return p


def mime_of(path: Path) -> str:
    """按扩展名给 MIME（在线预览用；未知类型按附件下载）。"""
    return PREVIEW_MIME.get(path.suffix.lower(), "application/octet-stream")


def sanitize_tags(raw: str | None) -> str | None:
    """标签清洗：中英文逗号/空白统一成单个逗号。"""
    if not raw:
        return None
    tags = [t for t in TAG_SANITIZE_RE.split(raw) if t]
    return ",".join(tags[:10]) if tags else None


def create_doc(db: Session, *, book_id: int, name: str, doc_type: str = "other",
               tags: str | None = None, doc_year: int | None = None,
               attachment_path: str | None = None, file_size: int = 0,
               source_model: str | None = None, source_id: int | None = None,
               remark: str | None = None, user_id: int = 1) -> DocDocument:
    now = datetime.now()
    doc = DocDocument(
        book_id=book_id, name=(name or "").strip()[:200], doc_type=doc_type,
        tags=sanitize_tags(tags), doc_year=doc_year,
        attachment_path=attachment_path, file_size=file_size,
        source_model=source_model, source_id=source_id, remark=remark,
        create_uid=user_id, create_date=now, write_uid=user_id, write_date=now,
        active=True,
    )
    db.add(doc)
    db.flush()
    return doc


def doc_to_dict(doc: DocDocument, book_name: str | None = None) -> dict:
    d = {
        "id": doc.id,
        "book_id": doc.book_id,
        "book_name": book_name,
        "name": doc.name,
        "doc_type": doc.doc_type,
        "tags": doc.tags,
        "doc_year": doc.doc_year,
        "attachment_path": doc.attachment_path,
        "file_size": doc.file_size,
        "source_model": doc.source_model,
        "source_id": doc.source_id,
        "remark": doc.remark,
        "create_date": doc.create_date.isoformat(sep=" ") if doc.create_date else None,
        "file_url": f"/api/v1/docs/{doc.id}/file" if doc.attachment_path else None,
        "previewable": bool(doc.attachment_path and Path(doc.attachment_path).suffix.lower()
                            in PREVIEW_MIME),
    }
    return d


def list_docs(db: Session, *, book_id: int | None = None, doc_type: str | None = None,
              tag: str | None = None, doc_year: int | None = None,
              search: str | None = None, source_model: str | None = None,
              limit: int = 100, offset: int = 0) -> tuple[int, list[dict]]:
    """跨账套文档列表（book_id 给了则按账套过滤），返回 (总数, 记录列表含客户名)。"""
    from ..res_partner.models import ResBook

    conds = [DocDocument.active.is_(True)]
    if book_id:
        conds.append(DocDocument.book_id == book_id)
    if doc_type:
        conds.append(DocDocument.doc_type == doc_type)
    if tag:
        conds.append(or_(DocDocument.tags.like(f"%{tag}%"),
                         DocDocument.tags.like(f"%,{tag}"),
                         DocDocument.tags == tag))
    if doc_year:
        conds.append(DocDocument.doc_year == doc_year)
    if source_model:
        conds.append(DocDocument.source_model == source_model)
    if search:
        kw = f"%{search.strip()}%"
        conds.append(or_(DocDocument.name.like(kw), DocDocument.remark.like(kw),
                         DocDocument.tags.like(kw)))

    q = select(DocDocument, ResBook.name).join(ResBook, DocDocument.book_id == ResBook.id) \
        .where(and_(*conds))
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(
        q.order_by(DocDocument.id.desc()).limit(limit).offset(offset)
    ).all()
    return total, [doc_to_dict(doc, book_name) for doc, book_name in rows]


def get_doc(db: Session, doc_id: int) -> DocDocument:
    doc = db.get(DocDocument, doc_id)
    if doc is None or not doc.active:
        raise BizError("not_found", "文档不存在或已删除")
    return doc


def update_doc(db: Session, doc: DocDocument, values: dict, user_id: int = 1) -> DocDocument:
    """只允许改元数据（名称/类型/标签/年份/备注/挂接），文件本身不换。"""
    allowed = {"name", "doc_type", "tags", "doc_year", "remark",
               "source_model", "source_id"}
    for k, v in values.items():
        if k not in allowed:
            continue
        if k == "tags":
            v = sanitize_tags(v)
        setattr(doc, k, v)
    doc.write_uid = user_id
    doc.write_date = datetime.now()
    db.flush()
    return doc


def find_by_source(db: Session, source_model: str, source_id: int) -> list[dict]:
    """反查某业务单据挂接的全部文档（DoD：从发票页上传 → 文档中心反查）。"""
    conds = [DocDocument.active.is_(True),
             DocDocument.source_model == source_model,
             DocDocument.source_id == source_id]
    rows = db.execute(select(DocDocument).where(and_(*conds))
                      .order_by(DocDocument.id)).scalars().all()
    return [doc_to_dict(d) for d in rows]


def doc_stats(db: Session) -> dict:
    """文档中心汇总（总数 / 各类型数量）。"""
    doc_type = DocDocument.doc_type
    rows = db.execute(
        select(doc_type.cast(String), func.count(DocDocument.id))
        .where(DocDocument.active.is_(True))
        .group_by(doc_type)
    ).all()
    by_type = {t: c for t, c in rows}
    return {"total": sum(by_type.values()), "by_type": by_type}
