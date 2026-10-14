"""幂等控制。

为什么需要两层防护
------------------
1. **应用层**（本模块）：在同一数据库事务内记录幂等键与响应快照，
   重复请求直接回放首次结果；
2. **数据层**：业务表上还有业务唯一约束（如报工表的 ``idempotency_key`` 唯一索引）。

即便应用层被绕过（例如有人直连数据库批量补数），第二层依然拦得住，
这正是简历中「幂等控制防止重复报工产生脏数据」所描述的完整含义。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import DuplicateReportError
from app.models.system import IdempotencyStatus, SysIdempotency
from app.utils import now, request_hash


def _find(db: Session, key: str, scope: str) -> SysIdempotency | None:
    return (
        db.query(SysIdempotency)
        .filter(SysIdempotency.idempotency_key == key, SysIdempotency.scope == scope)
        .first()
    )


def execute_idempotent(
    db: Session,
    *,
    key: str,
    scope: str,
    payload: Any,
    operator: str,
    handler: Callable[[], dict],
) -> tuple[dict, bool]:
    """以幂等方式执行写操作。

    :param db: 数据库会话（**必须**处于同一事务内，业务失败时幂等记录随之回滚）
    :param key: 幂等键，来自请求头 ``Idempotency-Key``
    :param scope: 业务域标识，不同业务的同名键互不干扰
    :param payload: 请求体，用于计算指纹
    :param operator: 操作人，便于追溯
    :param handler: 真正的业务闭包，返回可序列化的响应数据
    :return: ``(响应数据, 是否命中重复请求)``
    :raises DuplicateReportError: 首次请求仍在执行中，或同一键携带了不同参数
    """
    fingerprint = request_hash(payload)

    existing = _find(db, key, scope)
    if existing is None:
        record = SysIdempotency(
            idempotency_key=key,
            scope=scope,
            request_hash=fingerprint,
            status=IdempotencyStatus.IN_PROGRESS,
            operator=operator,
            expire_at=SysIdempotency.build_expire_at(settings.IDEMPOTENCY_TTL_SEC),
        )
        try:
            db.add(record)
            db.flush()          # 唯一约束冲突在此刻抛出
        except IntegrityError:
            # 并发场景下两个首次请求同时撞 unique 约束：先到者胜出
            db.rollback()
            raise DuplicateReportError("检测到并发重复提交，请稍后查询执行结果")
    else:
        if existing.request_hash != fingerprint:
            raise DuplicateReportError(
                f"幂等键 {key} 已被使用且请求参数不一致，请更换幂等键后重试"
            )
        if existing.status == IdempotencyStatus.SUCCEEDED:
            return json.loads(existing.response_snapshot or "{}"), True
        if existing.status == IdempotencyStatus.IN_PROGRESS:
            raise DuplicateReportError("上次相同请求正在处理中，请勿重复提交")
        # FAILED 状态允许原键重试
        record = existing
        record.status = IdempotencyStatus.IN_PROGRESS
        record.created_at = now()
        record.request_hash = fingerprint
        db.flush()

    result = handler()
    record.status = IdempotencyStatus.SUCCEEDED
    record.response_snapshot = json.dumps(result, default=str, ensure_ascii=False)
    db.flush()
    return result, False
