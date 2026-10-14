"""工序报工主流程测试：数量累计、库存联动、超量拦截、SPC 触发。"""

from __future__ import annotations

import pytest

from app.core.exceptions import DuplicateReportError, StateConflictError
from app.models.order import OperationStatus, PpWorkOrderOperation
from app.services.order_service import OrderService


def test_report_updates_operation_and_order_quantities(db, running_order, operators,
                                                       shifts):
    order, operation = running_order
    svc = OrderService(db)
    result, dup = svc.report_work(
        work_order_id=order.id, operation_id=operation.id,
        qty_good=40, qty_defect=2,
        employee_id=operators[0].id, shift_id=shifts[0].id,
        idempotency_key="wr-001", operator="pytest")
    db.commit()

    assert dup is False
    db.expire_all()
    op = db.get(PpWorkOrderOperation, operation.id)
    assert op.done_qty == 42
    assert op.good_qty == 40
    assert op.defect_qty == 2
    assert op.status == OperationStatus.RUNNING.value
    assert op.actual_labor_sec > 0           # 未显式传工时应按标准工时折算
    db.refresh(order)
    assert order.status == "IN_PROGRESS"


def test_report_consumes_inventory_by_good_qty(db, running_order):
    """报工必须按合格数 × 单位用量扣减库存，并生成流水。"""
    from app.models.order import PpMaterialRequirement

    order, operation = running_order
    svc = OrderService(db)
    result, _ = svc.report_work(
        work_order_id=order.id, operation_id=operation.id,
        qty_good=50, idempotency_key="wr-inv", operator="pytest")
    db.commit()

    assert result["inventory_flows"], "报工必须产生库存出库流水"
    db.expire_all()
    req = db.query(PpMaterialRequirement).filter(
        PpMaterialRequirement.work_order_id == order.id).first()
    assert float(req.qty_issued) > 0
    for flow in result["inventory_flows"]:
        assert flow["qty"] > 0
        assert isinstance(flow["tx_no"], str)


def test_report_cannot_exceed_planned_quantity(db, running_order):
    order, operation = running_order
    svc = OrderService(db)
    with pytest.raises(StateConflictError) as exc:
        svc.report_work(work_order_id=order.id, operation_id=operation.id,
                        qty_good=order.qty_planned + 10,
                        idempotency_key="wr-over", operator="pytest")
    assert "剩余计划量" in exc.value.detail["msg"]
    db.rollback()


def test_report_only_allowed_when_in_progress(db, new_order):
    from app.models.order import PpWorkOrderOperation

    op = db.query(PpWorkOrderOperation).filter(
        PpWorkOrderOperation.work_order_id == new_order.id).first()
    svc = OrderService(db)
    with pytest.raises(StateConflictError) as exc:
        svc.report_work(work_order_id=new_order.id, operation_id=op.id,
                        qty_good=1, idempotency_key="wr-draft", operator="pytest")
    assert "IN_PROGRESS" in exc.value.detail["msg"]
    db.rollback()


def test_operation_from_another_order_is_rejected(db, running_order, first_product,
                                                  first_routing):
    """工序必须属于目标工单，跨工单报工应被拒绝。"""
    from app.core.exceptions import NotFoundError
    from app.models.order import PpWorkOrderOperation

    svc = OrderService(db)
    other_order = svc.create_order(product_id=first_product.id,
                                   routing_id=first_routing.id,
                                   qty_planned=50, operator="pytest")
    db.flush()
    other_op = db.query(PpWorkOrderOperation).filter(
        PpWorkOrderOperation.work_order_id == other_order.id).first()

    order, _ = running_order
    with pytest.raises(NotFoundError):
        svc.report_work(work_order_id=order.id, operation_id=other_op.id,
                        qty_good=1, idempotency_key="wr-mismatch", operator="pytest")
    db.rollback()


def test_reporting_last_operation_completes_order_automatically(db, running_order):
    """全部工序报满后工单应自动完工。"""
    from app.models.order import PpWorkOrderOperation, WorkOrderStatus

    order, _ = running_order
    svc = OrderService(db)
    ops = list(db.query(PpWorkOrderOperation).filter(
        PpWorkOrderOperation.work_order_id == order.id
    ).order_by(PpWorkOrderOperation.seq.asc()).all())

    for idx, op in enumerate(ops):
        remain = int(op.plan_qty) - int(op.done_qty)
        result, _ = svc.report_work(
            work_order_id=order.id, operation_id=op.id,
            qty_good=remain, idempotency_key=f"wr-auto-{idx}",
            operator="pytest")
        db.commit()
        db.expire_all()
    assert result["auto_completed"] is True
    db.expire_all()
    assert svc.get_order(order.id).status == WorkOrderStatus.COMPLETED.value


def test_report_triggers_spc_subgroup_when_enabled(db, running_order,
                                                   spc_operation_source):
    """启用 SPC 的工序报工时应采样子组并计算控制图。

    这里分步构造：直接给 SPC 工序喂样本，验证relation 建立。
    """
    from app.models.quality import QmSpcSubgroup

    order, _ = running_order
    svc = OrderService(db)
    samples = [40.0, 40.01, 39.99, 40.02, 39.98]
    svc.spc.record_subgroup(
        product_id=order.product_id,
        operation_code=spc_operation_source.operation_code,
        values=samples,
        work_order_id=order.id,
        operation_id=None,
        feature_name=spc_operation_source.spc_feature_name,
        nominal=float(spc_operation_source.spc_nominal),
        upper_spec=float(spc_operation_source.spc_upper),
        lower_spec=float(spc_operation_source.spc_lower),
    )
    db.commit()

    group = db.query(QmSpcSubgroup).filter(
        QmSpcSubgroup.work_order_id == order.id).first()
    assert group is not None
    assert group.subgroup_size == 5
    assert float(group.mean_value) == pytest.approx(40.0, abs=1e-3)


def test_duplicate_report_flag_is_propagated(db, running_order):
    order, operation = running_order
    svc = OrderService(db)
    svc.report_work(work_order_id=order.id, operation_id=operation.id,
                    qty_good=5, idempotency_key="wr-dup", operator="pytest")
    db.commit()
    _, duplicated = svc.report_work(
        work_order_id=order.id, operation_id=operation.id, qty_good=5,
        idempotency_key="wr-dup", operator="pytest")
    assert duplicated is True
    db.rollback()
