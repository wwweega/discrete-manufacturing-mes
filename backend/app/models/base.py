"""ORM 公共定义。

包含三个通用组件：

* :class:`TimestampMixin` —— 创建/更新时间与软删除标记，所有业务表共享；
* :class:`StrEnum` —— 可被序列化的字符串枚举，DDL 中以 VARCHAR 落地，
  保证 MySQL 与 SQLite 行为完全一致（原生 Enum 在两库方言差异较大）；
* :func:`table_comment` —— 统一的表/字段注释工具，便于 DDL 评审。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """审计字段 + 软删除标记。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False,
        comment="更新时间",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否已逻辑删除"
    )
    remark: Mapped[str] = mapped_column(String(500), default="", nullable=False,
                                        comment="备注")


class StrEnum(str, Enum):
    """字符串枚举基类：写入数据库时落 `.value`。"""

    def __str__(self) -> str:  # pragma: no cover - 展示用途
        return str(self.value)

    @classmethod
    def values(cls) -> list[str]:
        return [item.value for item in cls]


def table_comment(text: str) -> dict:
    """返回表注释字典，供 `comment=` 参数使用。"""
    return {"comment": text}


def requires(column: bool = False):  # pragma: no cover - 占位工具，保持 API 兼容性
    """预留的必填声明工具，当前交由 ORM nullable 控制。"""
    return column
