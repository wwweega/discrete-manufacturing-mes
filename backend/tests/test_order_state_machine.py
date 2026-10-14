"""工单状态机测试：合法流转、非法流转、终态守卫。"""

from __future__ import annotations

import pytest

from app.core.exceptions import StateConflictError
from app.models.master import MdRoutingOperation
from app.models.order import PpMaterialRequirement, PpWorkOrderOperation, WorkOrderStatus
from app.models.order import allowed_order_targets
from app.services.order_service import OrderService


def test_new_order_is_draft(new_order):
    assert new_order.status == WorkOrderStatus.DRAFT.value
    assert new_order.qty_planned > 0
    assert new_order.version == 0


def test_order_expands_operations_from_routing(db, new_order, first_routing):
    """创建工单时必须按工艺路线展开工序（快照，不受路由后续变更影响）。"""
    expected = db.query(MdRoutingOperation).filter(
        MdRoutingOperation.routing_id == first_routing.id).count()
    actual = db.query(PpWorkOrderOperation).filter(
        PpWorkOrderOperation.work_order_id == new_order.id).count()
    assert actual == expected > 0


def test_material_requirements_expanded_from_bom(db, new_order):
    """物料需求 = 含损耗的单位用量 × 计划产量。"""
    requirements = db.query(PpMaterialRequirement).filter(
        PpMaterialRequirement.work_order_id == new_order.id).all()
    assert requirements
    for req in requirements:
        assert float(req.qty_required) == pytest.approx(
            float(req.unit_usage) * new_order.qty_planned, rel=1e-3)


def test_release_then_start_is_allowed(db, new_order):
    svc = OrderService(db)
    order = svc.transition(new_order.id, "RELEASED", "pytest")
    assert order.status == "RELEASED"
    assert order.released_by == "pytest"

    order = svc.transition(new_order.id, "IN_PROGRESS", "pytest")
    assert order.status == "IN_PROGRESS"
    assert order.actual_start is not None
    assert order.version >= 2


def test_illegal_transition_from_draft_to_completed(db, new_order):
    svc = OrderService(db)
    with pytest.raises(StateConflictError) as exc:
        svc.transition(new_order.id, "COMPLETED", "pytest")
    assert "不能流转" in exc.value.detail["msg"]


def test_cancelled_is_terminal(db, new_order):
    svc = OrderService(db)
    svc.transition(new_order.id, "CANCELLED", "pytest", reason="测试作废")
    assert WorkOrderStatus(svc.get_order(new_order.id).status).is_terminal is True
    with pytest.raises(StateConflictError):
        svc.transition(new_order.id, "RELEASED", "pytest")


def test_cannot_complete_when_operations_unfinished(db, running_order):
    order, _ = running_order
    svc = OrderService(db)
    with pytest.raises(StateConflictError) as exc:
        svc.transition(order.id, "COMPLETED", "pytest")
    assert "未完成" in exc.value.detail["msg"]


def test_allowed_transitions_matrix_is_consistent():
    assert allowed_order_targets("DRAFT") == ["CANCELLED", "RELEASED"]
    assert allowed_order_targets("COMPLETED") == []
    assert allowed_order_targets("UNKNOWN_STATUS") == []


def test_pause_and_resume(db, running_order):
    order, _ = running_order
    svc = OrderService(db)
    assert svc.transition(order.id, "PAUSED", "pytest", reason="设备维保").status == "PAUSED"
    assert svc.transition(order.id, "IN_PROGRESS", "pytest").status == "IN_PROGRESS"
