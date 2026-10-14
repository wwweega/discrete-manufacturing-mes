"""质量模块接口：质检单 + SPC 控制图。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_operator
from app.core.rbac import require_permissions
from app.core.response import ApiResponse, ok
from app.db.unit_of_work import transactional
from app.schemas.mes import (
    InspectionCreateRequest,
    InspectionRecordRequest,
    InspectionTransitionRequest,
    SPCAnalyzeRequest,
    SPCSampleRequest,
)
from app.services.quality_service import QualityService
from app.services.spc_core import analyze as analyze_samples
from app.services.spc_service import SPCService

router = APIRouter(prefix="/quality", tags=["质量管理"])

_VIEW = require_permissions("quality:view")


# --------------------------------------------------------------------------- SPC
@router.post(
    "/spc/subgroups",
    response_model=ApiResponse[dict],
    summary="录入 SPC 子组样本",
    description=(
        "按 X̄-R 控制图口径保存一个子组并重算控制限：\n\n"
        "- X̄ 图 UCL/LCL = X̄̄ ± A₂·R̄\n"
        "- R 图 UCL/LCL = D₄·R̄ / D₃·R̄\n\n"
        "若命中 GB/T 4091 判异准则，会**自动生成待处理质检单**。"
    ),
    dependencies=[Depends(require_permissions("spc:analyze"))],
)
def record_subgroup(payload: SPCSampleRequest, db: Session = Depends(get_db)) -> dict:
    service = SPCService(db)
    with transactional(db):
        result = service.record_subgroup(
            product_id=payload.product_id,
            operation_code=payload.operation_code,
            values=payload.values,
            feature_name=payload.feature_name,
            work_order_id=payload.work_order_id,
            operation_id=payload.operation_id,
            nominal=payload.nominal,
            upper_spec=payload.upper_spec,
            lower_spec=payload.lower_spec,
        )
    return ok(result)


@router.get(
    "/spc/chart/{product_id}/{operation_code}",
    response_model=ApiResponse[dict],
    summary="获取 X̄-R 控制图数据",
    description="返回 ECharts 可直接消费的均值/极差序列 + 中心线 + 上下控制限 + 异常点。",
    dependencies=[Depends(require_permissions("spc:view"))],
)
def control_chart(
    product_id: int,
    operation_code: str,
    tail: int = Query(30, ge=1, le=200, description="取最近子组数"),
    db: Session = Depends(get_db),
) -> dict:
    return ok(SPCService(db).get_control_chart(product_id, operation_code, tail))


@router.post(
    "/spc/analyze",
    response_model=ApiResponse[dict],
    summary="离线试算（不落库）",
    description="直接传入二维样本做试算，便于验证算法，不写入任何业务数据。",
    dependencies=[Depends(require_permissions("spc:view"))],
)
def analyze(payload: SPCAnalyzeRequest, db: Session = Depends(get_db)) -> dict:
    service = SPCService(db)
    result = service.analyze_series(payload.samples, upper_spec=payload.upper_spec,
                                    lower_spec=payload.lower_spec)
    return ok({
        "limits": SPCService._limits_payload(result),
        "means": result.means,
        "ranges": result.ranges,
        "violations": result.violations,
        "out_of_control": result.out_of_control,
    })


@router.get(
    "/spc/rules",
    response_model=ApiResponse[dict],
    summary="判异准则清单",
    dependencies=[Depends(require_permissions("spc:view"))],
)
def spc_rules(db: Session = Depends(get_db)) -> dict:
    return ok({"rules": SPCService.rule_descriptions()})


# --------------------------------------------------------------------------- 质检单
@router.get(
    "/tasks",
    response_model=ApiResponse[dict],
    summary="质检单列表",
    dependencies=[Depends(_VIEW)],
)
def list_tasks(
    status: str | None = Query(None),
    source: str | None = Query(None, description="SPC_ALERT / MANUAL / INCOMING"),
    work_order_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    service = QualityService(db)
    tasks = service.list_tasks(status=status, source=source,
                               work_order_id=work_order_id)
    return ok({
        "total": len(tasks),
        "items": [service.summarize_task(task) for task in tasks],
        "pending_count": service.pending_count(),
    })


@router.post(
    "/tasks",
    response_model=ApiResponse[dict],
    summary="人工发起质检单",
    dependencies=[Depends(require_permissions("quality:create"))],
)
def create_task(
    payload: InspectionCreateRequest,
    operator: str = Depends(get_operator),
    db: Session = Depends(get_db),
) -> dict:
    service = QualityService(db)
    with transactional(db):
        task = service.create_manual(
            product_id=payload.product_id,
            work_order_id=payload.work_order_id,
            operation_id=payload.operation_id,
            sample_qty=payload.sample_qty,
            inspector_no=operator,
            reason=payload.reason,
        )
        result = service.summarize_task(task)
    return ok(result)


@router.post(
    "/tasks/{task_id}/transition",
    response_model=ApiResponse[dict],
    summary="质检单流转",
    description="PENDING → TESTING → PASSED/FAILED → CLOSED。",
    dependencies=[Depends(require_permissions("quality:handle"))],
)
def transition_task(
    task_id: int,
    payload: InspectionTransitionRequest,
    operator: str = Depends(get_operator),
    db: Session = Depends(get_db),
) -> dict:
    service = QualityService(db)
    with transactional(db):
        task = service.transition(task_id, payload.target_status, operator)
        if payload.conclusion:
            task.conclusion = payload.conclusion
        result = service.summarize_task(task)
    return ok(result)


@router.post(
    "/tasks/{task_id}/records",
    response_model=ApiResponse[dict],
    summary="录入单件检验记录",
    description="按公差带自动判定 OK/NG，并回写抽检数量与不良数。",
    dependencies=[Depends(require_permissions("quality:handle"))],
)
def add_record(
    task_id: int,
    payload: InspectionRecordRequest,
    db: Session = Depends(get_db),
) -> dict:
    service = QualityService(db)
    with transactional(db):
        record = service.add_record(
            task_id=task_id,
            seq=payload.seq,
            measured_value=payload.measured_value,
            nominal=payload.nominal,
            tolerance_upper=payload.tolerance_upper,
            tolerance_lower=payload.tolerance_lower,
            defect_type_id=payload.defect_type_id,
            feature_name=payload.feature_name,
        )
        result = {
            "id": record.id, "seq": record.seq,
            "measured_value": float(record.measured_value),
            "result": record.result,
        }
    return ok(result)
