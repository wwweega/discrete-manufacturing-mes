"""库存管理接口：发料、退料、盘点调整、流水查询。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_operator
from app.core.rbac import require_permissions
from app.core.response import ApiResponse, ok
from app.db.unit_of_work import transactional
from app.models.inventory import MmInventoryStock, MmInventoryTransaction, MmMaterial
from app.models.master import MdWarehouse
from app.schemas.mes import IssueMaterialRequest, MaterialReturnRequest, StockAdjustRequest
from app.services.inventory_service import InventoryService

router = APIRouter(prefix="/inventory", tags=["库存管理"])

_VIEW = require_permissions("inventory:view")


@router.get(
    "",
    response_model=ApiResponse[dict],
    summary="库存余额列表",
    description="物料 × 仓库维度的当前结存，联动安全库存给出预警标记。",
    dependencies=[Depends(_VIEW)],
)
def list_stock(
    material_id: int | None = Query(None),
    warehouse_id: int | None = Query(None),
    only_low: bool = Query(False, description="仅看低于安全库存的物料"),
    db: Session = Depends(get_db),
) -> dict:
    stmt = (
        select(
            MmInventoryStock,
            MmMaterial.code, MmMaterial.name, MmMaterial.unit,
            MmMaterial.safety_stock, MmMaterial.spec,
            MdWarehouse.name.label("warehouse_name"),
        )
        .join(MmMaterial, MmMaterial.id == MmInventoryStock.material_id)
        .join(MdWarehouse, MdWarehouse.id == MmInventoryStock.warehouse_id)
    )
    if material_id:
        stmt = stmt.where(MmInventoryStock.material_id == material_id)
    if warehouse_id:
        stmt = stmt.where(MmInventoryStock.warehouse_id == warehouse_id)

    rows = db.execute(stmt).all()
    items = []
    for stock, code, name, unit, safety, spec, wh_name in rows:
        on_hand = float(stock.qty_on_hand or 0)
        items.append({
            "material_id": stock.material_id,
            "warehouse_id": stock.warehouse_id,
            "warehouse_name": wh_name,
            "material_code": code,
            "material_name": name,
            "spec": spec,
            "unit": unit,
            "qty_on_hand": round(on_hand, 3),
            "qty_reserved": round(float(stock.qty_reserved or 0), 3),
            "qty_available": round(on_hand - float(stock.qty_reserved or 0), 3),
            "safety_stock": float(safety or 0),
            "below_safety": on_hand < float(safety or 0),
            "last_tx_at": stock.last_tx_at,
        })
    if only_low:
        items = [i for i in items if i["below_safety"]]
    return ok({
        "total": len(items),
        "low_stock_count": sum(1 for i in items if i["below_safety"]),
        "items": items,
    })


@router.get(
    "/transactions",
    response_model=ApiResponse[dict],
    summary="库存流水",
    description="任意库存变动都留有流水，含变动前后余额，支持按单据追溯。",
    dependencies=[Depends(_VIEW)],
)
def list_transactions(
    material_id: int | None = Query(None),
    work_order_id: int | None = Query(None),
    tx_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(MmInventoryTransaction)
    if material_id:
        stmt = stmt.where(MmInventoryTransaction.material_id == material_id)
    if work_order_id:
        stmt = stmt.where(MmInventoryTransaction.work_order_id == work_order_id)
    if tx_type:
        stmt = stmt.where(MmInventoryTransaction.tx_type == tx_type)
    rows = db.execute(
        stmt.order_by(MmInventoryTransaction.id.desc()).limit(limit)
    ).scalars().all()

    items = [{
        "tx_no": tx.tx_no, "material_id": tx.material_id,
        "warehouse_id": tx.warehouse_id, "tx_type": tx.tx_type,
        "direction": tx.direction, "qty": float(tx.qty),
        "balance_after": float(tx.balance_after),
        "ref_type": tx.ref_type, "ref_id": tx.ref_id,
        "work_order_id": tx.work_order_id, "operator_no": tx.operator_no,
        "tx_time": tx.tx_time,
    } for tx in rows]
    summary = {
        "in_qty": round(sum(i["qty"] for i in items if i["direction"] == 1), 3),
        "out_qty": round(sum(i["qty"] for i in items if i["direction"] == -1), 3),
    }
    return ok({"total": len(items), "items": items, "summary": summary})


@router.post(
    "/issue",
    response_model=ApiResponse[dict],
    summary="工单发料（出库）",
    description="库存不足时直接返回 409 并回滚，绝不允许出现负库存。",
    dependencies=[Depends(require_permissions("inventory:issue"))],
)
def issue_material(
    payload: IssueMaterialRequest,
    operator: str = Depends(get_operator),
    db: Session = Depends(get_db),
) -> dict:
    service = InventoryService(db)
    with transactional(db):
        tx = service.issue(
            material_id=payload.material_id,
            warehouse_id=payload.warehouse_id,
            qty=payload.qty,
            ref_type="MANUAL_ISSUE",
            work_order_id=payload.work_order_id,
            operator_no=payload.operator_no or operator,
        )
        result = {
            "tx_no": tx.tx_no, "qty": float(tx.qty),
            "balance_after": float(tx.balance_after),
        }
    return ok(result)


@router.post(
    "/return",
    response_model=ApiResponse[dict],
    summary="工单退料",
    description="退料量不得超过已发放量，系统会自动取较小值。",
    dependencies=[Depends(require_permissions("inventory:issue"))],
)
def return_material(
    payload: MaterialReturnRequest,
    operator: str = Depends(get_operator),
    db: Session = Depends(get_db),
) -> dict:
    service = InventoryService(db)
    with transactional(db):
        tx = service.return_material(
            work_order_id=payload.work_order_id,
            material_id=payload.material_id,
            qty=payload.qty,
            operator_no=payload.operator_no or operator,
        )
        result = {"tx_no": tx.tx_no, "qty": float(tx.qty),
                  "balance_after": float(tx.balance_after)}
    return ok(result)


@router.post(
    "/adjust",
    response_model=ApiResponse[dict],
    summary="盘点调整",
    description="把账面数量调整为指定值，差额自动生成一条 ADJUST 流水。",
    dependencies=[Depends(require_permissions("inventory:adjust"))],
)
def adjust_stock(
    payload: StockAdjustRequest,
    operator: str = Depends(get_operator),
    db: Session = Depends(get_db),
) -> dict:
    service = InventoryService(db)
    with transactional(db):
        tx = service.adjust(
            material_id=payload.material_id,
            warehouse_id=payload.warehouse_id,
            target_qty=payload.target_qty,
            operator_no=payload.operator_no or operator,
            reason=payload.reason,
        )
        result = {
            "adjusted": tx is not None,
            "tx_no": tx.tx_no if tx else "",
            "balance_after": float(tx.balance_after) if tx else payload.target_qty,
        }
    return ok(result)
