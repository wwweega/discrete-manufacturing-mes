"""SPC、库存、质量相关 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SPCSampleRequest(BaseModel):
    """手动录入一个 SPC 子组。"""

    model_config = ConfigDict(json_schema_extra={"example": {
        "product_id": 1, "operation_code": "OP20",
        "values": [10.02, 10.01, 9.99, 10.03, 10.00],
        "feature_name": "内孔直径", "upper_spec": 10.05, "lower_spec": 9.95,
        "nominal": 10.0,
    }})

    product_id: int = Field(..., gt=0)
    operation_code: str = Field(..., min_length=1, max_length=32)
    values: list[float] = Field(..., description="子组样本值，建议 n=4~5")
    feature_name: str = Field("关键尺寸", max_length=64)
    nominal: float = Field(0.0, description="目标值")
    upper_spec: float = Field(0.0, description="规格上限 USL")
    lower_spec: float = Field(0.0, description="规格下限 LSL")
    work_order_id: Optional[int] = Field(None, gt=0)
    operation_id: Optional[int] = Field(None, gt=0)

    @field_validator("values")
    @classmethod
    def check_size(cls, v: list[float]) -> list[float]:
        if not 2 <= len(v) <= 10:
            raise ValueError("子组容量 n 需在 2~10 之间（X̄-R 图要求）")
        return v

    @field_validator("lower_spec")
    @classmethod
    def check_spec(cls, v: float, info) -> float:
        upper = info.data.get("upper_spec") or 0.0
        if upper and v and v >= upper:
            raise ValueError("规格下限必须小于规格上限")
        return v


class SPCAnalyzeRequest(BaseModel):
    """纯计算（不落库）的批量样本分析，用于预演。"""

    samples: list[list[float]] = Field(..., description="二维样本：每个子组一组数值")
    upper_spec: float = 0.0
    lower_spec: float = 0.0


class InspectionCreateRequest(BaseModel):
    """人工发起质检单。"""

    product_id: int = Field(..., gt=0)
    work_order_id: Optional[int] = Field(None, gt=0)
    operation_id: Optional[int] = Field(None, gt=0)
    sample_qty: int = Field(5, ge=1, le=500)
    reason: str = Field("人工报检", max_length=200)


class InspectionTransitionRequest(BaseModel):
    target_status: str = Field(..., description="TESTING/PASSED/FAILED/CLOSED")
    conclusion: str = Field("", max_length=500)


class InspectionRecordRequest(BaseModel):
    seq: int = Field(..., ge=1)
    measured_value: float = Field(..., description="实测值")
    nominal: float = Field(0.0)
    tolerance_upper: float = Field(0.0)
    tolerance_lower: float = Field(0.0)
    feature_name: str = Field("", max_length=64)
    defect_type_id: Optional[int] = Field(None, gt=0)


class IssueMaterialRequest(BaseModel):
    """工单发料 / 退料。"""

    material_id: int = Field(..., gt=0)
    warehouse_id: int = Field(..., gt=0)
    qty: float = Field(..., gt=0, description="数量，必须大于 0")
    work_order_id: Optional[int] = Field(None, gt=0)
    operator_no: str = Field("", max_length=32)


class MaterialReturnRequest(BaseModel):
    work_order_id: int = Field(..., gt=0)
    material_id: int = Field(..., gt=0)
    qty: float = Field(..., gt=0)
    operator_no: str = Field("", max_length=32)


class StockAdjustRequest(BaseModel):
    material_id: int = Field(..., gt=0)
    warehouse_id: int = Field(..., gt=0)
    target_qty: float = Field(..., ge=0, description="调整后的账面数量")
    operator_no: str = Field("", max_length=32)
    reason: str = Field("盘点调整", max_length=200)


class StockView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    material_id: int
    warehouse_id: int
    qty_on_hand: float
    qty_reserved: float
    qty_in_transit: float
    last_tx_at: Optional[datetime] = None
