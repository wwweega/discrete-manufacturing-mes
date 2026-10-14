"""基础数据（主数据）只读接口，供前端下拉框与演示查看。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.core.rbac import require_permissions
from app.core.response import ApiResponse, ok
from app.models import count_tables
from app.models.master import (
    MdBom,
    MdBomItem,
    MdEmployee,
    MdEquipment,
    MdProduct,
    MdProductionLine,
    MdRouting,
    MdRoutingOperation,
    MdShift,
    MdWarehouse,
    MdWorkshop,
)
from app.models.inventory import MmMaterial

router = APIRouter(prefix="/master", tags=["基础数据"])

_VIEW = require_permissions("master:view")
_MANAGE = require_permissions("master:manage")


def _dump(rows, fields: tuple[str, ...]) -> list[dict]:
    return [{field: getattr(row, field) for field in fields} for row in rows]


@router.get(
    "",
    response_model=ApiResponse[dict],
    summary="基础数据总览（一次性返回全部档案）",
    dependencies=[Depends(_VIEW)],
)
def all_master(db: Session = Depends(get_db)) -> dict:
    return ok({
        "workshops": _dump(db.query(MdWorkshop).all(), ("id", "code", "name", "manager")),
        "lines": _dump(db.query(MdProductionLine).all(),
                       ("id", "code", "name", "workshop_id", "capacity_per_hour")),
        "equipments": _dump(db.query(MdEquipment).all(),
                            ("id", "code", "name", "model", "line_id", "status")),
        "employees": _dump(db.query(MdEmployee).all(),
                           ("id", "emp_no", "name", "position", "status")),
        "shifts": _dump(db.query(MdShift).all(), ("id", "code", "name", "start_time", "end_time")),
        "products": _dump(db.query(MdProduct).all(),
                          ("id", "code", "name", "spec", "unit", "std_cycle_sec")),
        "boms": _dump(db.query(MdBom).all(), ("id", "bom_code", "product_id", "version")),
        "bom_items": _dump(db.query(MdBomItem).all(),
                           ("id", "bom_id", "material_id", "qty_per_unit", "loss_rate")),
        "routings": _dump(db.query(MdRouting).all(),
                          ("id", "routing_code", "routing_name", "product_id")),
        "routing_operations": _dump(db.query(MdRoutingOperation).all(),
                                    ("id", "routing_id", "seq", "operation_code",
                                     "operation_name", "std_time_sec", "qc_required",
                                     "spc_enabled", "spc_upper", "spc_lower",
                                     "spc_nominal", "spc_subgroup_size")),
        "warehouses": _dump(db.query(MdWarehouse).all(), ("id", "code", "name", "category")),
        "materials": _dump(db.query(MmMaterial).all(),
                           ("id", "code", "name", "spec", "unit", "safety_stock")),
        "table_count": count_tables(),
    })


@router.get(
    "/health",
    response_model=ApiResponse[dict],
    summary="系统健康检查",
    description="返回数据表数量、当前登录用户与基础档案条数，用于部署后自检。",
)
def health(current_user=Depends(get_current_user),
           db: Session = Depends(get_db)) -> dict:
    return ok({
        "status": "UP",
        "tables": count_tables(),
        "user": current_user.username,
        "counts": {
            "workshop": db.query(MdWorkshop).count(),
            "product": db.query(MdProduct).count(),
            "equipment": db.query(MdEquipment).count(),
            "material": db.query(MmMaterial).count(),
            "employee": db.query(MdEmployee).count(),
        },
    })
