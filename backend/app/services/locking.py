"""锁工具：跨方言的行级排他锁。

MySQL InnoDB 支持 ``SELECT ... FOR UPDATE``；SQLite 不支持该语法，
单写者模式下退化为普通读取即可（同一进程内的 SQLite 写操作本身串行）。
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.core.config import settings

T = TypeVar("T")


def lock_row(db: Session, stmt: Select) -> Any:
    """在当前会话内锁定目标行；SQLite 下按普通查询处理。"""
    if not settings.is_sqlite:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalars().first()
