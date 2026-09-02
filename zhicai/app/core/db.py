# -*- coding: utf-8 -*-
"""数据库引擎与会话工厂：SQLite + WAL 模式（项目书 4.1/9 章）。"""
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import CONFIG

# check_same_thread=False：FastAPI 多线程访问；真正的写串行由 SQLite 单写者特性保证
engine = create_engine(
    f"sqlite:///{CONFIG.db_path}",
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _record):
    """每个连接开启 WAL / 外键 / 忙等待，对齐 Odoo 对数据库底座的严格要求。"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：请求级会话，异常回滚。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
