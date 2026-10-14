"""工单相关 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.order import WorkOrderStatus


class OrderCreateRequest(BaseModel):
    """创建工单入参。"""

    model_config = ConfigDict(json_schema_extra={"example": {
        "product_id": 1, "routing_id": 1, "qty_planned": 500,
        "priority": 3, "bom_id": 1,
    }})

    product_id: int = Field(..., gt=0, description="产品 ID")
    routing_id: int = Field(..., gt=0, description="工艺路线 ID")
    qty_planned: int = Field(..., gt=0, le=1_000_000, description="计划产量")
    priority: int = Field(5, ge=1, le=9, description="优先级 1~9，越小越紧急")
    workshop_id: Optional[int] = Field(None, gt=0)
    line_id: Optional[int] = Field(None, gt=0)
    bom_id: Optional[int] = Field(None, gt=0, description="不传则取产品默认启用 BOM")
    plan_start: Optional[datetime] = None
    plan_end: Optional[datetime] = None
    owner_group: str = Field("", max_length=32, description="责任班组")

    @field_validator("plan_end")
    @classmethod
    def check_time_range(cls, v: Optional[datetime], info) -> Optional[datetime]:
        start = info.data.get("plan_start")
        if v and start and v < start:
            raise ValueError("计划完工时间不能早于计划开工时间")
        return v


class OrderTransitionRequest(BaseModel):
    """工单状态流转入参。"""

    model_config = ConfigDict(json_schema_extra={"example": {
        "target_status": "RELEASED", "reason": "计划排产下达"
    }})

    target_status: str = Field(..., description="目标状态")
    reason: str = Field("", max_length=200, description="作废 / 暂停原因")

    @field_validator("target_status")
    @classmethod
    def check_status(cls, v: str) -> str:
        allowed = {item.value for item in WorkOrderStatus}
        if v not in allowed:
            raise ValueError(f"非法状态，可选值：{sorted(allowed)}")
        return v


class WorkReportRequest(BaseModel):
    """工序报工入参。"""

    model_config = ConfigDict(json_schema_extra={"example": {
        "operation_id": 1, "qty_good": 100, "qty_defect": 2,
        "employee_id": 1, "shift_id": 1,
        "measurements": [10.02, 10.01, 9.99, 10.03, 10.00],
        "idempotency_key": "report-wo-1-op-1-001",
    }})

    operation_id: int = Field(..., gt=0, description="工序 ID（工单工序）")
    qty_good: int = Field(..., ge=0, le=1_000_000, description="合格数")
    qty_defect: int = Field(0, ge=0, le=1_000_000, description="不良数")
    employee_id: Optional[int] = Field(None, gt=0)
    shift_id: Optional[int] = Field(None, gt=0)
    labor_sec: int = Field(0, ge=0, description="实际人工秒；不传则按标准工时折算")
    machine_sec: int = Field(0, ge=0, description="实际机器秒")
    measurements: list[float] = Field(default_factory=list, description="SPC 子组样本值")
    idempotency_key: Optional[str] = Field(
        None, max_length=128,
        description="幂等键；重复携带同一值可安全重放，不会产生第二笔报工",
    )

    @field_validator("qty_good")
    @classmethod
    def at_least_one(cls, v: int, info) -> int:
        if v == 0 and int(info.data.get("qty_defect") or 0) == 0:
            raise ValueError("合格数与不良数不能同时为 0")
        return v

    @field_validator("measurements")
    @classmethod
    def check_samples(cls, v: list[float]) -> list[float]:
        if len(v) > 10:
            raise ValueError("单次采样最多 10 个样本（X̄-R 图推荐 4~5 个）")
        return v


class OrderBrief(BaseModel):
    """工单列表项。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    product_id: int
    status: str
    priority: int
    qty_planned: int
    qty_completed: int
    qty_good: int
    qty_defect: int
    owner_group: str = ""
    created_at: Optional[datetime] = None


class OperationBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int
    operation_code: str
    operation_name: str
    plan_qty: int
    done_qty: int
    good_qty: int
    defect_qty: int
    status: str
    std_time_sec: int
    spc_enabled: bool = False
    qc_required: bool = False


class MaterialRequirementBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_id: int
    warehouse_id: int
    qty_required: float
    qty_issued: float
    qty_returned: float
    unit_usage: float


class OrderDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    product_id: int
    status: str
    qty_planned: int
    qty_completed: int
    qty_good: int
    qty_defect: int
    priority: int
    plan_start: Optional[datetime] = None
    plan_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    released_by: str = ""
    owner_group: str = ""
    version: int = 0
