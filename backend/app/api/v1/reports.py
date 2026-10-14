"""8 张统计报表接口。

全部报表均为**多表关联 SQL**，返回结构已适配 ECharts 与通用列表两种消费方式。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.rbac import require_permissions
from app.core.response import ApiResponse, ok
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["统计报表"])

_VIEW = require_permissions("report:view")


@router.get(
    "",
    response_model=ApiResponse[list],
    summary="报表目录",
    description="返回 8 张报表的编号、名称与所属模块。",
    dependencies=[Depends(_VIEW)],
)
def catalog() -> dict:
    return ok(ReportService.catalog())


@router.get(
    "/{code}",
    response_model=ApiResponse[dict],
    summary="按编号查询报表",
    description=(
        "可用编号：\n\n"
        "1. `work_order_progress` 工单进度报表\n"
        "2. `yield_rate` 良品率报表\n"
        "3. `equipment_oee` 设备稼动率报表\n"
        "4. `output_daily` 产量日报表\n"
        "5. `operation_efficiency` 工序工时效率报表\n"
        "6. `defect_pareto` 质量不良柏拉图\n"
        "7. `inventory_turnover` 库存周转报表\n"
        "8. `worker_performance` 人员绩效报表"
    ),
    dependencies=[Depends(_VIEW)],
)
def query_report(
    code: str,
    days: int = Query(30, ge=1, le=365, description="统计窗口天数"),
    status: str | None = Query(None, description="工单进度报表专用：状态过滤"),
    work_order_id: int | None = Query(None, description="工序工时报表专用：工单过滤"),
    db: Session = Depends(get_db),
) -> dict:
    service = ReportService(db)
    kwargs: dict = {"days": days}
    if status and code == "work_order_progress":
        kwargs["status"] = status
    if work_order_id and code == "operation_efficiency":
        kwargs["work_order_id"] = work_order_id
    return ok(service.dispatch(code, **kwargs))
