"""系统支撑模型（1 张表）。

``sys_idempotency`` 是幂等控制的基础设施：

写接口（报工、发料、排产）要求客户端在 Header 中携带 ``Idempotency-Key``，
服务端在**同一事务内**把「键 + 请求指纹 + 响应快照」落库；重复请求命中已完成的键时，
直接返回首次执行的响应快照，而不是再执行一次业务。
配合业务表上的业务唯一约束，形成应用层 + 数据层的双重防护。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin, table_comment


class IdempotencyStatus:
    """幂等记录状态常量。"""

    IN_PROGRESS = "IN_PROGRESS"  # 首次请求执行中
    SUCCEEDED = "SUCCEEDED"      # 首次请求已成功
    FAILED = "FAILED"            # 首次请求已失败（可重试）


class SysIdempotency(Base, TimestampMixin):
    """幂等键记录表。"""

    __tablename__ = "sys_idempotency"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uk_sys_idempotency_key"),
        table_comment("幂等键记录表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="幂等键")
    scope: Mapped[str] = mapped_column(String(64), default="", nullable=False,
                                       comment="业务域，如 work_report/issue_material")
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False,
                                              comment="请求体指纹，防止同键不同参数")
    response_snapshot: Mapped[str] = mapped_column(String(4000), default="", nullable=False,
                                                   comment="首次执行结果快照JSON")
    status: Mapped[str] = mapped_column(String(16), default=IdempotencyStatus.IN_PROGRESS,
                                        nullable=False)
    operator: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime, comment="过期时间")

    @classmethod
    def build_expire_at(cls, ttl_seconds: int) -> datetime:
        """计算过期时间（UTC-naive 存储，与 MySQL/SQLite 一致）。"""
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=ttl_seconds)
