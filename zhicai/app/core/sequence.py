# -*- coding: utf-8 -*-
"""自动编号（对标 Odoo ir.sequence，项目书 5.3.4）。

凭证号规则：{凭证字}-{YYYYMM}-{0001}，按 账套+编号器+月份 重置计数；
SQLite 单写者特性天然防并发重号。
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..modules.base.models import IrSequence
from .errors import BizError


def next_number(db: Session, code: str, *, book_id: int | None = None, period: str | None = None) -> str:
    """取下一个编号并落库计数。

    code: 编号器代码，如 "move.journal.记"
    period: 传 YYYYMM 时按月重置（凭证号场景）
    返回值：prefix + 序号（padding 补零）
    """
    stmt = select(IrSequence).where(
        IrSequence.code == code,
        IrSequence.book_id == book_id if book_id is not None else IrSequence.book_id.is_(None),
    )
    seq = db.execute(stmt).scalar_one_or_none()
    if seq is None:
        raise BizError("sequence_missing", f"编号器不存在：{code}（book={book_id}）")

    # 按月重置
    if period is not None and seq.number_prefix != period:
        seq.number_prefix = period
        seq.next_number = 1

    n = seq.next_number
    seq.next_number = n + 1
    db.flush()
    return f"{seq.prefix}{n:0{seq.padding}d}"


def ensure_sequence(db: Session, code: str, prefix: str, *, name: str | None = None,
                    book_id: int | None = None,
                    padding: int = 4, start: int = 1) -> IrSequence:
    """创建编号器（幂等）。"""
    stmt = select(IrSequence).where(
        IrSequence.code == code,
        IrSequence.book_id == book_id if book_id is not None else IrSequence.book_id.is_(None),
    )
    seq = db.execute(stmt).scalar_one_or_none()
    if seq is not None:
        return seq
    seq = IrSequence(code=code, name=name or code, prefix=prefix, padding=padding,
                     next_number=start, book_id=book_id)
    db.add(seq)
    db.flush()
    return seq
