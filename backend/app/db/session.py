"""数据库引擎与会话管理。

* MySQL：生产 / Docker Compose 部署形态，连接池按配置初始化；
* SQLite：本地演示形态，零依赖运行（自动创建 data 目录，关闭同线程检查）。
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    pass


def _build_engine() -> Engine:
    """按配置构建 SQLAlchemy Engine。"""
    if settings.is_sqlite:
        db_path = Path(settings.SQLITE_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            settings.database_url,
            echo=settings.SQL_ECHO,
            future=True,
            connect_args={"check_same_thread": False},
        )

        # SQLite 默认不强制外键，显式开启以保证级联约束与 MySQL 行为一致
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):  # pragma: no cover
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    return create_engine(
        settings.database_url,
        echo=settings.SQL_ECHO,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=3600,
    )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                            expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖项：请求级别的数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(drop_first: bool = False) -> None:
    """创建全部业务表（幂等）。"""
    from app.models import load_all_models  # 局部导入避免循环依赖

    load_all_models()
    if drop_first:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
