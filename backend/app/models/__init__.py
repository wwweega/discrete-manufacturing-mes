"""ORM 模型包。

业务表合计 **31 张**（简历口径：20+ 张业务表），按模块划分为 7 组，见 README 表格。
统一在此处 import 并导出，保证 ``Base.metadata`` 在任何建表时机都已注册完全部表。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase

from app.db.session import Base, engine
from app.models.base import TimestampMixin
from app.models.equipment import EqAlarm, EqStatusLog
from app.models.inventory import (
    MmInventoryStock,
    MmInventoryTransaction,
    MmMaterial,
    TransactionType,
)
from app.models.master import (
    EquipmentStatus,
    MdBom,
    MdBomItem,
    MdEmployee,
    MdEquipment,
    MdProductionLine,
    MdProduct,
    MdRouting,
    MdRoutingOperation,
    MdShift,
    MdSupplier,
    MdWarehouse,
    MdWorkshop,
)
from app.models.order import (
    OperationStatus,
    WORK_ORDER_TRANSITIONS,
    allowed_order_targets,
    PpMaterialRequirement,
    PpWorkOrder,
    PpWorkOrderOperation,
    PpWorkReport,
    WorkOrderStatus,
)
from app.models.quality import (
    InspectionSource,
    InspectionStatus,
    QmDefectType,
    QmInspectionRecord,
    QmInspectionTask,
    QmSpcSubgroup,
)
from app.models.rbac import (
    SysPermission,
    SysRole,
    SysRolePermission,
    SysUser,
    SysUserRole,
)
from app.models.system import IdempotencyStatus, SysIdempotency

__all__ = [
    # 基础设施
    "Base", "engine", "TimestampMixin",
    # RBAC（5）
    "SysUser", "SysRole", "SysPermission", "SysUserRole", "SysRolePermission",
    # 主数据（12）
    "MdWorkshop", "MdProductionLine", "MdEmployee", "MdShift", "MdEquipment",
    "MdProduct", "MdBom", "MdBomItem", "MdRouting", "MdRoutingOperation",
    "MdWarehouse", "MdSupplier", "EquipmentStatus",
    # 库存（3）
    "MmMaterial", "MmInventoryStock", "MmInventoryTransaction", "TransactionType",
    # 工单（4）
    "PpWorkOrder", "PpWorkOrderOperation", "PpWorkReport", "PpMaterialRequirement",
    "WorkOrderStatus", "OperationStatus", "WORK_ORDER_TRANSITIONS",
    "allowed_order_targets",
    # 质量（4）
    "QmDefectType", "QmInspectionTask", "QmInspectionRecord", "QmSpcSubgroup",
    "InspectionStatus", "InspectionSource",
    # 设备（2）
    "EqStatusLog", "EqAlarm",
    # 系统（1）
    "SysIdempotency", "IdempotencyStatus",
]

#: 是否为首次加载（模块级幂等标志）
_LOADED = False


def load_all_models() -> type[DeclarativeBase]:
    """确保所有模型类被导入、元数据注册完成。

    返回 Base，便于 ``Base.metadata.create_all(engine)`` 直接使用。
    """
    global _LOADED
    if not _LOADED:
        _LOADED = True
    return Base


def count_tables() -> int:
    """返回已注册的业务表数量，用于自检与文档一致性校验。"""
    return len(Base.metadata.tables)
