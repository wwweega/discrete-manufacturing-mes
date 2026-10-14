"""报工幂等控制测试（简历重点：防止重复报工产生脏数据）。"""

from __future__ import annotations

import pytest

from app.core.exceptions import DuplicateReportError, StateConflictError
from app.models.order import PpWorkReport
from app.services.order_service import OrderService


def _report(db, order, operation, *, qty: int = 20, key: str | None = "k-1"):
    return OrderService(db).report_work(
        work_order_id=order.id,
        operation_id=operation.id,
        qty_good=qty,
        qty_defect=0,
        idempotency_key=key,
        operator="pytest",
    )


def test_duplicate_report_returns_same_result(db, running_order):
    """同一幂等键重复提交：第二次返回首次结果，且不产生第二笔数据。"""
    order, operation = running_order

    first, dup_flag = _report(db, order, operation, key="dup-key-001")
    db.commit()
    assert dup_flag is False

    db.expire_all()
    second, dup_flag2 = _report(db, order, operation, key="dup-key-001")
    db.commit()

    assert dup_flag2 is True
    assert first["report_no"] == second["report_no"]
    assert db.query(PpWorkReport).filter(
        PpWorkReport.work_order_id == order.id).count() == 1


def test_same_key_with_different_params_is_rejected(db, running_order):
    """同一幂等键 + 不同参数必须被拒绝，避免误导性的静默覆盖。"""
    order, operation = running_order
    _report(db, order, operation, qty=20, key="dup-key-002")
    db.commit()

    db.expire_all()
    with pytest.raises(DuplicateReportError):
        _report(db, order, operation, qty=30, key="dup-key-002")


def test_different_keys_create_separate_reports(db, running_order):
    order, operation = running_order
    first, _ = _report(db, order, operation, qty=15, key="key-a")
    db.commit()
    db.expire_all()
    second, dup = _report(db, order, operation, qty=15, key="key-b")
    db.commit()
    assert dup is False
    assert first["report_no"] != second["report_no"]
    assert db.query(PpWorkReport).filter(
        PpWorkReport.work_order_id == order.id).count() == 2


def test_idempotency_record_persisted(db, running_order):
    """幂等键必须落库，且与业务写入处于同一事务（业务回滚则记录回滚）。"""
    from app.models.system import IdempotencyStatus, SysIdempotency

    order, operation = running_order
    _report(db, order, operation, key="persist-key")
    db.commit()

    record = db.query(SysIdempotency).filter(
        SysIdempotency.idempotency_key == "persist-key").first()
    assert record is not None
    assert record.status == IdempotencyStatus.SUCCEEDED
    assert "report_no" in record.response_snapshot


def test_report_rolls_back_idempotency_record_on_failure(db, running_order):
    """业务失败时幂等记录一起回滚，同一键可安全重试。"""
    from app.models.system import SysIdempotency

    order, operation = running_order
    order_id, operation_id = int(order.id), int(operation.id)

    with pytest.raises(StateConflictError):
        # 数量超出计划量 → 业务异常
        OrderService(db).report_work(
            work_order_id=order_id, operation_id=operation_id,
            qty_good=order.qty_planned + 1, idempotency_key="retry-key",
            operator="pytest")
    db.rollback()

    assert db.query(SysIdempotency).filter(
        SysIdempotency.idempotency_key == "retry-key").first() is None

    # 同一键重试成功（回滚后旧 ORM 对象已失效，这里只依赖主键重新发起）
    result, dup = OrderService(db).report_work(
        work_order_id=order_id, operation_id=operation_id,
        qty_good=10, idempotency_key="retry-key", operator="pytest")
    db.commit()
    assert dup is False and result["qty_good"] == 10


def test_unique_constraint_blocks_direct_duplicate_insert(db, running_order):
    """绕过应用层直接插入重复幂等键，数据库唯一约束仍应拦截。"""
    from sqlalchemy.exc import IntegrityError

    from app.models.order import PpWorkReport

    order, operation = running_order
    _report(db, order, operation, key="db-level-key")
    db.commit()

    duplicate = PpWorkReport(
        report_no="RP-MANUAL-001",
        work_order_id=order.id,
        operation_id=operation.id,
        qty_good=1,
        report_time=order.created_at,
        idempotency_key="db-level-key",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
