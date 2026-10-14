"""库存模型（3 张表）。

mm_material（物料档案）→ mm_inventory_stock（当前库存）→
mm_inventory_transaction（库存流水）。

所有库存变更**必须**落流水：报工扣料、退料、采购入库、盘点调整，
流水表记录变更前后的结存余额，用于对账与库存周转报表。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import StrEnum, TimestampMixin, table_comment


class TransactionType(StrEnum):
    """库存流水类型。"""

    PURCHASE_IN = "PURCHASE_IN"    # 采购入库
    WORK_ORDER_ISSUE = "WO_ISSUE"  # 工单领料（投产扣减）
    RETURN = "RETURN"              # 退料
    FINISH_IN = "FINISH_IN"        # 完工入库
    ADJUST = "ADJUST"              # 盘点调整
    SCRAP_OUT = "SCRAP_OUT"        # 报废出库


class MmMaterial(Base, TimestampMixin):
    """物料档案。"""

    __tablename__ = "mm_material"
    __table_args__ = (
        UniqueConstraint("code", name="uk_mm_material_code"),
        table_comment("物料档案表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="物料编码")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    spec: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="PCS", nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="RAW", nullable=False,
                                          comment="物料类别")
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("md_supplier.id"))
    unit_price: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False)
    safety_stock: Mapped[float] = mapped_column(Numeric(18, 3), default=0.0, nullable=False,
                                                comment="安全库存")
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class MmInventoryStock(Base, TimestampMixin):
    """库存余额（物料 × 仓库 唯一）。"""

    __tablename__ = "mm_inventory_stock"
    __table_args__ = (
        UniqueConstraint("material_id", "warehouse_id", name="uk_mm_stock"),
        table_comment("库存余额表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("mm_material.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("md_warehouse.id"), nullable=False)
    qty_on_hand: Mapped[float] = mapped_column(Numeric(18, 3), default=0.0, nullable=False,
                                               comment="账面在库量")
    qty_reserved: Mapped[float] = mapped_column(Numeric(18, 3), default=0.0, nullable=False,
                                                comment="已预留（冻结）量")
    qty_in_transit: Mapped[float] = mapped_column(Numeric(18, 3), default=0.0, nullable=False,
                                                  comment="在途量")
    last_tx_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最近变动时间")

    @property
    def qty_available(self) -> float:
        """可用量 = 在库 - 预留。"""
        return float(self.qty_on_hand) - float(self.qty_reserved)


class MmInventoryTransaction(Base, TimestampMixin):
    """库存流水，任何变更必有记录。"""

    __tablename__ = "mm_inventory_transaction"
    __table_args__ = (
        UniqueConstraint("tx_no", name="uk_mm_tx_no"),
        table_comment("库存流水表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tx_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="流水单号")
    material_id: Mapped[int] = mapped_column(ForeignKey("mm_material.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("md_warehouse.id"), nullable=False)
    tx_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="流水类型")
    direction: Mapped[int] = mapped_column(Integer, nullable=False, comment="1入库 -1出库")
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False, comment="变动量（正数）")
    balance_after: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False,
                                                 comment="变动后在库量")
    ref_type: Mapped[str] = mapped_column(String(32), default="", nullable=False,
                                          comment="来源单据类型")
    ref_id: Mapped[str] = mapped_column(String(64), default="", nullable=False,
                                        comment="来源单据号")
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("pp_work_order.id"))
    operator_no: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    tx_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="业务发生时间")
