"""8 张统计报表测试：结构完整性 + 关键指标正确性。"""

from __future__ import annotations

import pytest

from app.services.order_service import OrderService
from app.services.report_service import REPORT_CATALOG, ReportService


@pytest.fixture()
def data_ready(db, running_order, operators, shifts) -> dict:
    """把工单全部工序报满并完工，形成可统计的完整数据。"""
    from app.models.order import PpWorkOrderOperation

    order, first_operation = running_order
    svc = OrderService(db)
    ops = list(db.query(PpWorkOrderOperation).filter(
        PpWorkOrderOperation.work_order_id == order.id
    ).order_by(PpWorkOrderOperation.seq.asc()).all())

    for idx, op in enumerate(ops):
        remain = int(op.plan_qty) - int(op.done_qty)
        if remain <= 0:
            continue
        defect = min(3, remain - 1)
        svc.report_work(work_order_id=order.id, operation_id=op.id,
                        qty_good=remain - defect, qty_defect=defect,
                        employee_id=operators[0].id, shift_id=shifts[0].id,
                        idempotency_key=f"rep-{idx}", operator="pytest")
        db.commit()
        db.expire_all()
    db.commit()
    return {"order": order, "operation": first_operation}


def test_catalog_contains_eight_reports():
    catalog = ReportService.catalog()
    assert len(catalog) == 8
    assert {item["code"] for item in catalog} == {
        "work_order_progress", "yield_rate", "equipment_oee", "output_daily",
        "operation_efficiency", "defect_pareto", "inventory_turnover",
        "worker_performance",
    }


def test_work_order_progress_report(db, data_ready):
    result = ReportService(db).work_order_progress()
    assert result["summary"]["qty_planned"] >= 100
    assert 0 <= result["summary"]["achieve_rate"] <= 100
    for item in result["items"]:
        assert item["progress"] == pytest.approx(
            item["qty_completed"] / item["qty_planned"] * 100, abs=0.05)


def test_yield_rate_report(db, data_ready):
    result = ReportService(db).yield_rate()
    items = result["items"]
    assert items, "有报工数据时应产出良品率记录"
    for item in items:
        assert item["yield_rate"] + item["defect_rate"] == pytest.approx(100.0, abs=0.2)
    assert 0 <= result["summary"]["overall_yield_rate"] <= 100


def test_equipment_oee_report(db, data_ready):
    from app.realtime.device_gateway import DeviceGateway

    DeviceGateway(write_db=True).tick()
    db.commit()
    result = ReportService(db).equipment_oee()
    assert result["summary"]["equipment_count"] > 0
    assert result["summary"]["window_seconds"] > 0
    for item in result["items"]:
        assert 0 <= item["availability"] <= 100


def test_output_daily_report(db, data_ready):
    result = ReportService(db).output_daily(days=7)
    assert result["summary"]["total_good"] >= 60
    assert result["items"], "存在报工即有日产出数据"
    assert isinstance(result["top_products"], list)


def test_operation_efficiency_report(db, data_ready):
    result = ReportService(db).operation_efficiency()
    assert result["items"], "有报工即有工序效率数据"
    for item in result["items"]:
        assert item["std_seconds"] >= 0
        assert item["efficiency"] >= 0


def test_report_dispatch_by_code(db, data_ready):
    svc = ReportService(db)
    for item in REPORT_CATALOG:
        payload = svc.dispatch(item["code"], days=30)
        assert isinstance(payload, dict)
        assert "items" in payload and "summary" in payload


def test_unknown_report_code_raises(db):
    with pytest.raises(KeyError):
        ReportService(db).dispatch("not_exist_report")
