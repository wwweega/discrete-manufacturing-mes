"""生产工单接口。

所有写操作通过 ``dependencies=[Depends(require_permissions(...))]``
声明所需权限码，实现**接口级** RBAC（对应简历「基于 RBAC 实现接口级权限控制」）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_operator
from app.core.exceptions import StateConflictError
from app.core.rbac import require_permissions
from app.core.response import ApiResponse, ok
from app.db.unit_of_work import transactional
from app.models.order import WorkOrderStatus, allowed_order_targets
from app.schemas.order import (
    OrderCreateRequest,
    OrderDetailResponse,
    OrderTransitionRequest,
    WorkReportRequest,
)
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["生产工单"])

_VIEW = require_permissions("order:view")


@router.get(
    "",
    response_model=ApiResponse[dict],
    summary="工单列表",
    dependencies=[Depends(_VIEW)],
)
def list_orders(
    status: str | None = Query(None, description="按状态过滤"),
    product_id: int | None = Query(None, description="按产品过滤"),
    keyword: str | None = Query(None, description="工单号模糊匹配"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    service = OrderService(db)
    rows = service.list_orders(status=status, product_id=product_id,
                               keyword=keyword, limit=limit)
    items = [{
        "id": r.id, "order_no": r.order_no, "product_id": r.product_id,
        "status": r.status, "priority": r.priority,
        "qty_planned": r.qty_planned, "qty_completed": r.qty_completed,
        "qty_good": r.qty_good, "qty_defect": r.qty_defect,
        "owner_group": r.owner_group, "created_at": r.created_at,
        "progress": r.progress, "yield_rate": r.yield_rate,
    } for r in rows]
    return ok({"items": items, "total": len(items)})


@router.post(
    "",
    response_model=ApiResponse[dict],
    summary="创建工单（草稿）",
    description="按工艺路线自动展开工序、按 BOM 自动展开物料需求。",
    dependencies=[Depends(require_permissions("order:create"))],
)
def create_order(
    payload: OrderCreateRequest,
    operator: str = Depends(get_operator),
    db: Session = Depends(get_db),
) -> dict:
    service = OrderService(db)
    with transactional(db):
        order = service.create_order(
            product_id=payload.product_id,
            routing_id=payload.routing_id,
            qty_planned=payload.qty_planned,
            priority=payload.priority,
            workshop_id=payload.workshop_id,
            line_id=payload.line_id,
            bom_id=payload.bom_id,
            plan_start=payload.plan_start,
            plan_end=payload.plan_end,
            owner_group=payload.owner_group,
            operator=operator,
        )
        result = {
            "id": order.id,
            "order_no": order.order_no,
            "status": order.status,
            "qty_planned": order.qty_planned,
        }
    return ok(result)


@router.get(
    "/status-machine",
    response_model=ApiResponse[dict],
    summary="工单状态机定义",
    description="返回状态机的合法流转表，前端据此动态渲染可用操作按钮。",
    dependencies=[Depends(_VIEW)],
)
def status_machine() -> dict:
    return ok({
        state.value: allowed_order_targets(state.value)
        for state in WorkOrderStatus
    })


@router.get(
    "/{order_id}",
    response_model=ApiResponse[dict],
    summary="工单详情",
    description="含工序清单、物料需求、最近 20 条报工流水与当前可执行的状态流转。",
    dependencies=[Depends(_VIEW)],
)
def order_detail(order_id: int, db: Session = Depends(get_db)) -> dict:
    detail = OrderService(db).detail(order_id)
    return ok({
        "order": OrderDetailResponse.model_validate(detail["order"]).model_dump(),
        "operations": [{
            "id": op.id, "seq": op.seq, "operation_code": op.operation_code,
            "operation_name": op.operation_name, "plan_qty": op.plan_qty,
            "done_qty": op.done_qty, "good_qty": op.good_qty,
            "defect_qty": op.defect_qty, "status": op.status,
            "std_time_sec": op.std_time_sec, "spc_enabled": op.spc_enabled,
            "qc_required": op.qc_required, "progress": op.progress,
            "equipment_id": op.equipment_id,
        } for op in detail["operations"]],
        "materials": [{
            "id": m.id, "material_id": m.material_id, "warehouse_id": m.warehouse_id,
            "material_code": detail["material_names"].get(m.material_id, ("", "", ""))[0],
            "material_name": detail["material_names"].get(m.material_id, ("", "", ""))[1],
            "unit": detail["material_names"].get(m.material_id, ("", "", ""))[2],
            "qty_required": float(m.qty_required), "qty_issued": float(m.qty_issued),
            "qty_returned": float(m.qty_returned), "unit_usage": float(m.unit_usage),
        } for m in detail["materials"]],
        "reports": [{
            "report_no": r.report_no, "qty_good": r.qty_good,
            "qty_defect": r.qty_defect, "report_time": r.report_time,
        } for r in detail["reports"]],
        "allowed_transitions": detail["allowed_transitions"],
        "summary": detail["summary"],
    })


@router.post(
    "/{order_id}/transition",
    response_model=ApiResponse[dict],
    summary="工单状态流转",
    description=(
        "统一的状态机流转入口：下达 / 开工 / 暂停恢复 / 完工 / 作废。\n\n"
        "非法流转会返回 409 并给出可读原因；完工时会自动校验全部工序是否完成，"
        "并触发合格品入库。"
    ),
    dependencies=[Depends(require_permissions("order:release", "order:start",
                                              "order:complete", "order:cancel"))],
)
def transition(
    order_id: int,
    payload: OrderTransitionRequest,
    operator: str = Depends(get_operator),
    db: Session = Depends(get_db),
) -> dict:
    service = OrderService(db)
    with transactional(db):
        order = service.transition(order_id, payload.target_status, operator,
                                   payload.reason)
        result = {
            "id": order.id, "order_no": order.order_no, "status": order.status,
            "version": order.version,
            "allowed_transitions": allowed_order_targets(order.status),
        }
    return ok(result)


@router.post(
    "/{order_id}/report",
    response_model=ApiResponse[dict],
    summary="工序报工",
    description=(
        "**系统核心写操作**，具备四重保护：\n\n"
        "1. **幂等**：请求头 `Idempotency-Key` 相同则回放首次结果，不会产生第二笔数据；\n"
        "2. **状态机**：仅 `IN_PROGRESS` 工单可报工；\n"
        "3. **超量校验**：累计报工不得超过工序计划量；\n"
        "4. **单事务**：报工 + 库存扣料 + SPC 采样子组 + 自动完工，同成功同失败。\n\n"
        "命中重复请求时返回 `duplicated=true`，数据与首次执行完全一致。"
    ),
    dependencies=[Depends(require_permissions("order:report"))],
)
def report_work(
    order_id: int,
    payload: WorkReportRequest,
    idempotency_key: str | None = Header(
        None, alias="Idempotency-Key",
        description="幂等键，建议由客户端生成全局唯一值（UUID）",
    ),
    operator: str = Depends(get_operator),
    db: Session = Depends(get_db),
) -> dict:
    service = OrderService(db)
    with transactional(db):
        result, duplicated = service.report_work(
            work_order_id=order_id,
            operation_id=payload.operation_id,
            qty_good=payload.qty_good,
            qty_defect=payload.qty_defect,
            employee_id=payload.employee_id,
            shift_id=payload.shift_id,
            labor_sec=payload.labor_sec,
            machine_sec=payload.machine_sec,
            measurements=payload.measurements,
            idempotency_key=payload.idempotency_key or idempotency_key,
            operator=operator,
        )
    result["duplicated"] = duplicated
    result["message"] = "本次请求为重复提交，已返回首次执行结果" if duplicated else "报工成功"
    return ok(result)


@router.get(
    "/{order_id}/allowed-transitions",
    response_model=ApiResponse[dict],
    summary="查询当前可流转状态",
    dependencies=[Depends(_VIEW)],
)
def allowed_transitions(order_id: int, db: Session = Depends(get_db)) -> dict:
    return ok({"transitions": OrderService(db).allowed_transitions(order_id)})
