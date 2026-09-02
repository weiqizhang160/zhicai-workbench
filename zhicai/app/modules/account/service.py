# -*- coding: utf-8 -*-
"""account 模块服务：账套初始化（克隆科目模板 + 默认账簿 + 凭证编号器）。

对标 Odoo chart_template 的模板克隆机制（项目书 6.3 约束）。
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import BizError
from ...core.sequence import ensure_sequence
from .models import AccountAccount, AccountJournal
from .seed_coa import COA_ENTERPRISE, COA_SMALL, DEFAULT_JOURNALS


def init_book_accounting(db: Session, book_id: int, standard: str = "small") -> dict:
    """为账套初始化会计基础数据（幂等保护：已有科目则拒绝）。

    返回 {"accounts": 数量, "journals": 数量}
    """
    existed = db.execute(
        select(AccountAccount.id).where(AccountAccount.book_id == book_id).limit(1)
    ).scalar_one_or_none()
    if existed is not None:
        raise BizError("coa_exists", "该账套已初始化科目表，不能重复初始化")

    template = COA_SMALL if standard != "enterprise" else COA_ENTERPRISE

    # 两遍法：第一遍全部插入（flush 拿 id），第二遍回填 parent_id 与 is_leaf
    has_children = {row[4] for row in template if row[4]}
    by_code: dict[str, AccountAccount] = {}
    for code, name, acc_type, direction, _parent, aux in template:
        acc = AccountAccount(
            code=code, name=name, account_type=acc_type, direction=direction,
            is_leaf=code not in has_children,
            auxiliary_flags=aux, book_id=book_id,
        )
        db.add(acc)
        by_code[code] = acc
    db.flush()  # 生成主键，供 parent 回填
    for code, _name, _t, _d, parent, _a in template:
        if parent:
            by_code[code].parent_id = by_code[parent].id

    # 默认账簿（凭证字）
    for code, name, jtype in DEFAULT_JOURNALS:
        db.add(AccountJournal(code=code, name=name, journal_type=jtype, book_id=book_id))

    # 凭证编号器：每账套 × 每凭证字（记-202609-0001 格式，按月重置）
    for code, name, _t in DEFAULT_JOURNALS:
        ensure_sequence(db, f"move.{book_id}.{code}", name=f"{name}凭证编号", prefix=f"{code}-",
                        book_id=book_id, padding=4)

    db.flush()
    return {"accounts": len(template), "journals": len(DEFAULT_JOURNALS)}


def book_account_count(db: Session, book_id: int) -> int:
    return len(db.execute(
        select(AccountAccount.id).where(AccountAccount.book_id == book_id, AccountAccount.active.is_(True))
    ).scalars().all())
