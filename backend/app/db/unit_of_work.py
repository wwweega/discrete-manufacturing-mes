"""事务上下文管理。

统一「正常提交 / 异常回滚」语义，避免每个接口重复 try-except。
服务层只负责 ``flush``，事务边界由调用方（API 层）决定 —— 这样同一个服务方法
既能在 HTTP 请求里用，也能被后台任务或单元测试复用。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session


@contextmanager
def transactional(db: Session) -> Iterator[Session]:
    """包裹一段需要原子提交的写操作。"""
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


@contextmanager
def readonly(db: Session) -> Iterator[Session]:
    """只读场景的语法糖：保证任何异常都不会留下半截事务。"""
    try:
        yield db
    except Exception:
        db.rollback()
        raise
