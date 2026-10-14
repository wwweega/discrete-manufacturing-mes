"""Schema 包入口。"""

from app.schemas.common import (
    LoginRequest,
    MessageResponse,
    ORMModel,
    PageResult,
    Pagination,
    TokenResponse,
)
from app.schemas.mes import (
    InspectionCreateRequest,
    InspectionRecordRequest,
    InspectionTransitionRequest,
    IssueMaterialRequest,
    MaterialReturnRequest,
    SPCAnalyzeRequest,
    SPCSampleRequest,
    StockAdjustRequest,
    StockView,
)
from app.schemas.order import (
    MaterialRequirementBrief,
    OperationBrief,
    OrderBrief,
    OrderCreateRequest,
    OrderDetailResponse,
    OrderTransitionRequest,
    WorkReportRequest,
)

__all__ = [
    "ORMModel", "Pagination", "PageResult", "LoginRequest", "TokenResponse",
    "MessageResponse",
    "OrderCreateRequest", "OrderTransitionRequest", "WorkReportRequest",
    "OrderBrief", "OperationBrief", "OrderDetailResponse",
    "MaterialRequirementBrief",
    "SPCSampleRequest", "SPCAnalyzeRequest", "InspectionCreateRequest",
    "InspectionTransitionRequest", "InspectionRecordRequest",
    "IssueMaterialRequest", "MaterialReturnRequest", "StockAdjustRequest", "StockView",
]
