"""库存联动测试：扣减、流水、不足拦截、退料、盘点调整。"""

from __future__ import annotations

import pytest

from app.core.exceptions import InventoryShortageError
from app.models.inventory import (
    MmInventoryStock,
    MmInventoryTransaction,
    MmMaterial,
    TransactionType,
)
from app.models.master import MdWarehouse
from app.services.inventory_service import InventoryService


@pytest.fixture()
def raw_warehouse(db):
    return db.query(MdWarehouse).filter(MdWarehouse.category == "RAW").first()


@pytest.fixture()
def steel(db):
    return db.query(MmMaterial).filter(MmMaterial.code == "RM-STEEL45").first()


def _stock(db, material_id: int, warehouse_id: int) -> float:
    row = db.query(MmInventoryStock).filter(
        MmInventoryStock.material_id == material_id,
        MmInventoryStock.warehouse_id == warehouse_id).first()
    return float(row.qty_on_hand) if row else 0.0


def test_issue_deducts_stock_and_writes_transaction(db, steel, raw_warehouse):
    svc = InventoryService(db)
    before = _stock(db, steel.id, raw_warehouse.id)

    tx = svc.issue(material_id=steel.id, warehouse_id=raw_warehouse.id,
                   qty=100.0, operator_no="pytest")
    db.commit()

    assert tx.tx_type == TransactionType.WORK_ORDER_ISSUE.value
    assert tx.direction == -1
    assert _stock(db, steel.id, raw_warehouse.id) == pytest.approx(before - 100.0)
    assert float(tx.balance_after) == pytest.approx(before - 100.0)


def test_receive_increases_stock(db, steel, raw_warehouse):
    svc = InventoryService(db)
    before = _stock(db, steel.id, raw_warehouse.id)
    svc.receive(material_id=steel.id, warehouse_id=raw_warehouse.id, qty=500.0)
    db.commit()
    assert _stock(db, steel.id, raw_warehouse.id) == pytest.approx(before + 500.0)


def test_shortage_raises_and_rolls_back(db, steel, raw_warehouse):
    svc = InventoryService(db)
    before = _stock(db, steel.id, raw_warehouse.id)
    with pytest.raises(InventoryShortageError) as exc:
        svc.issue(material_id=steel.id, warehouse_id=raw_warehouse.id,
                  qty=before + 1_000_000)
    db.rollback()
    assert "库存不足" in exc.value.detail["msg"]
    assert _stock(db, steel.id, raw_warehouse.id) == pytest.approx(before)


def test_every_change_creates_transaction(db, steel, raw_warehouse):
    svc = InventoryService(db)
    start = db.query(MmInventoryTransaction).count()
    svc.receive(material_id=steel.id, warehouse_id=raw_warehouse.id, qty=10.0)
    svc.issue(material_id=steel.id, warehouse_id=raw_warehouse.id, qty=4.0)
    svc.adjust(material_id=steel.id, warehouse_id=raw_warehouse.id,
               target_qty=1_000.0)
    db.commit()
    assert db.query(MmInventoryTransaction).count() == start + 3


def test_adjust_sets_exact_balance(db, steel, raw_warehouse):
    svc = InventoryService(db)
    tx = svc.adjust(material_id=steel.id, warehouse_id=raw_warehouse.id,
                    target_qty=777.0, operator_no="pytest")
    db.commit()
    assert _stock(db, steel.id, raw_warehouse.id) == pytest.approx(777.0)
    assert tx.tx_type == TransactionType.ADJUST.value


def test_transaction_records_balance_after(db, steel, raw_warehouse):
    svc = InventoryService(db)
    tx = svc.issue(material_id=steel.id, warehouse_id=raw_warehouse.id, qty=33.0)
    db.commit()
    stock = db.query(MmInventoryStock).filter(
        MmInventoryStock.material_id == steel.id,
        MmInventoryStock.warehouse_id == raw_warehouse.id).first()
    assert float(tx.balance_after) == pytest.approx(float(stock.qty_on_hand))


def test_consume_for_report_respects_planned_total(db, new_order, steel, raw_warehouse):
    """累计发料不得超过工单计划需求量。"""
    from app.models.order import PpMaterialRequirement

    svc = InventoryService(db)
    req = db.query(PpMaterialRequirement).filter(
        PpMaterialRequirement.work_order_id == new_order.id).first()
    planned = float(req.qty_required)

    flows = svc.consume_for_report(work_order_id=new_order.id,
                                   good_qty=new_order.qty_planned,
                                   operator_no="pytest")
    flows += svc.consume_for_report(work_order_id=new_order.id,
                                    good_qty=new_order.qty_planned,
                                    operator_no="pytest")
    db.commit()

    db.expire_all()
    req = db.query(PpMaterialRequirement).filter(
        PpMaterialRequirement.work_order_id == new_order.id).first()
    assert float(req.qty_issued) <= planned + 1e-6
    assert flows, "首次报工应产生领料流水"


def test_return_material_reverses_issued_quantity(db, new_order):
    from app.models.order import PpMaterialRequirement

    svc = InventoryService(db)
    req = db.query(PpMaterialRequirement).filter(
        PpMaterialRequirement.work_order_id == new_order.id).first()

    svc.issue(material_id=req.material_id, warehouse_id=req.warehouse_id, qty=50.0,
              ref_type="WORK_REPORT", work_order_id=new_order.id)
    req.qty_issued = 50.0
    db.flush()

    svc.return_material(work_order_id=new_order.id, material_id=req.material_id,
                        qty=20.0)
    db.commit()
    db.expire_all()
    req = db.query(PpMaterialRequirement).filter(
        PpMaterialRequirement.work_order_id == new_order.id).first()
    assert float(req.qty_issued) == pytest.approx(30.0)
    assert float(req.qty_returned) == pytest.approx(20.0)


def test_ensure_stock_creates_zero_row_when_missing(db, steel, raw_warehouse):
    svc = InventoryService(db)
    stock = svc.ensure_stock(steel.id, raw_warehouse.id)
    db.commit()
    assert stock is not None
    assert float(stock.qty_on_hand) >= 0.0
