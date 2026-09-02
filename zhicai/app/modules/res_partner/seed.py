# -*- coding: utf-8 -*-
"""res_partner 模块种子：2 个示例账套（完整走 create_book 初始化链路）。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .models import ResBook

DEMO_BOOKS = [
    {
        "name": "深圳市宏发五金制品有限公司",
        "short_name": "宏发五金",
        "credit_no": "91440300MA5DA1234X",
        "taxpayer_type": "general",
        "accounting_standard": "small",
        "is_foreign_trade": False,
        "industry": "五金制品",
        "legal_person": "张宏",
        "phone": "0755-12345678",
        "address": "深圳市宝安区XX街道XX号",
        "bookkeeping_start": "2026-01-01",
    },
    {
        "name": "深圳市远洋进出口贸易有限公司",
        "short_name": "远洋外贸",
        "credit_no": "91440300MA5EX5678Y",
        "taxpayer_type": "general",
        "accounting_standard": "small",
        "is_foreign_trade": True,
        "industry": "进出口贸易",
        "legal_person": "李远",
        "phone": "0755-87654321",
        "address": "深圳市南山区XX路XX号",
        "bookkeeping_start": "2026-01-01",
    },
]


def seed(db: Session):
    """幂等：仅当库中无任何账套时创建示例账套（真实数据后不再自动造示例）。"""
    has_book = db.execute(select(ResBook.id).limit(1)).scalar_one_or_none()
    if has_book is not None:
        return
    for payload in DEMO_BOOKS:
        service.create_book(db, payload, user_id=None)
    db.flush()
