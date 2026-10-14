"""数据访问层（Repository）。

职责边界：**只做 SQL 封装**，不含业务规则判断；
所有写操作的状态变更、事务边界统一由 service 层编排。

提供三类通用能力：

* :class:`BaseRepository` —— 主键 CRUD + 软删除；
* :func:`paginate` —— 统一分页执行，返回 PageData 结构；
* 各业务 Repository —— 复杂多表关联查询集中于此。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.response import PageData
from app.db.session import Base

ModelT = TypeVar("ModelT", bound=Base)


def paginate(db: Session, stmt: Select, page: int, page_size: int) -> tuple[list[Any], int]:
    """执行分页查询。

    计数语句剥离 ORDER BY 以避免 MySQL/SQLite 上的无效排序开销。
    """
    page = max(page, 1)
    page_size = min(max(page_size, 1), settings.MAX_PAGE_SIZE)

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return list(rows), total


def build_page(items: list, total: int, page: int, page_size: int) -> PageData:
    """构造分页结果模型。"""
    page = max(page, 1)
    page_size = min(max(page_size, 1), settings.MAX_PAGE_SIZE)
    pages = (total + page_size - 1) // page_size if page_size else 0
    return PageData(items=items, total=total, page=page, page_size=page_size, pages=pages)


class BaseRepository(Generic[ModelT]):
    """通用仓储基类。"""

    model: type[ModelT]

    def __init__(self, db: Session):
        self.db = db

    def get(self, pk: int) -> ModelT | None:
        return self.db.get(self.model, pk)

    def get_or_raise(self, pk: int, msg: str = "记录不存在") -> ModelT:
        obj = self.get(pk)
        if obj is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(msg)
        return obj

    def get_by(self, **filters: Any) -> ModelT | None:
        stmt = select(self.model).filter_by(**filters)
        return self.db.execute(stmt).scalars().first()

    def list_all(self, **filters: Any) -> list[ModelT]:
        stmt = select(self.model).filter_by(**filters)
        return list(self.db.execute(stmt).scalars().unique().all())

    def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model).filter_by(**filters)
        return int(self.db.execute(stmt).scalar_one())

    def save(self, obj: ModelT) -> ModelT:
        self.db.add(obj)
        self.db.flush()
        return obj
