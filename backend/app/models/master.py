"""主数据模型（12 张表）。

覆盖离散制造车间基础档案：

车间 → 产线 → 设备 三级生产资源，员工 / 班次，
产品 → BOM / 工艺路线（含工序）两层产品定义，以及仓库、供应商。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import StrEnum, TimestampMixin, table_comment


class EquipmentStatus(StrEnum):
    """设备运行状态。"""

    RUN = "RUN"            # 运行
    IDLE = "IDLE"          # 待机
    FAULT = "FAULT"        # 故障
    MAINTAIN = "MAINTAIN"  # 维保
    OFFLINE = "OFFLINE"    # 离线（超过心跳窗口未上报）


# ------------------------------------------------------------------ 生产资源
class MdWorkshop(Base, TimestampMixin):
    """车间。"""

    __tablename__ = "md_workshop"
    __table_args__ = (
        UniqueConstraint("code", name="uk_md_workshop_code"),
        table_comment("车间档案表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, comment="车间编码")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="车间名称")
    location: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    manager: Mapped[str] = mapped_column(String(64), default="", nullable=False, comment="负责人")
    capacity_per_day: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                                  comment="日产能基数（件）")


class MdProductionLine(Base, TimestampMixin):
    """产线 / 工作中心。"""

    __tablename__ = "md_production_line"
    __table_args__ = (
        UniqueConstraint("code", name="uk_md_line_code"),
        table_comment("产线（工作中心）档案表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("md_workshop.id"), nullable=False)
    capacity_per_hour: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                                   comment="小时产能（件）")
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class MdEmployee(Base, TimestampMixin):
    """员工（操作员 / 质检员 / 班组长）。"""

    __tablename__ = "md_employee"
    __table_args__ = (
        UniqueConstraint("emp_no", name="uk_md_employee_no"),
        table_comment("员工档案表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    emp_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="工号")
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    workshop_id: Mapped[int | None] = mapped_column(ForeignKey("md_workshop.id"))
    position: Mapped[str] = mapped_column(String(32), default="OPERATOR", nullable=False,
                                          comment="OPERATOR/INSPECTOR/LEADER")
    hire_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class MdShift(Base, TimestampMixin):
    """班次。"""

    __tablename__ = "md_shift"
    __table_args__ = (
        UniqueConstraint("code", name="uk_md_shift_code"),
        table_comment("班次档案表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    start_time: Mapped[str] = mapped_column(String(8), nullable=False, comment="HH:MM:SS")
    end_time: Mapped[str] = mapped_column(String(8), nullable=False)
    duration_hour: Mapped[float] = mapped_column(Numeric(4, 1), default=8.0, nullable=False,
                                                 comment="班次时长（小时）")


class MdEquipment(Base, TimestampMixin):
    """设备台账。"""

    __tablename__ = "md_equipment"
    __table_args__ = (
        UniqueConstraint("code", name="uk_md_equipment_code"),
        table_comment("设备台账表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, comment="设备编码")
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    workshop_id: Mapped[int | None] = mapped_column(ForeignKey("md_workshop.id"))
    line_id: Mapped[int | None] = mapped_column(ForeignKey("md_production_line.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("md_supplier.id"))
    # 与前端仪表盘上报频次对齐的静态属性
    status: Mapped[str] = mapped_column(String(16), default=EquipmentStatus.IDLE.value,
                                        nullable=False, comment="设备状态")
    rated_speed: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                             comment="额定转速(r/min)")
    rated_output: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                              comment="额定小时产量(件)")
    purchase_date: Mapped[date | None] = mapped_column(Date)
    next_maintain_at: Mapped[datetime | None] = mapped_column(DateTime)


# ------------------------------------------------------------------ 产品定义
class MdProduct(Base, TimestampMixin):
    """产品 / 物料成品。"""

    __tablename__ = "md_product"
    __table_args__ = (
        UniqueConstraint("code", name="uk_md_product_code"),
        table_comment("产品档案表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    spec: Mapped[str] = mapped_column(String(128), default="", nullable=False, comment="规格型号")
    unit: Mapped[str] = mapped_column(String(16), default="PCS", nullable=False)
    version: Mapped[str] = mapped_column(String(16), default="V1.0", nullable=False)
    std_cycle_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                               comment="标准单件工时（秒）")
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class MdBom(Base, TimestampMixin):
    """BOM 主表。"""

    __tablename__ = "md_bom"
    __table_args__ = (
        UniqueConstraint("bom_code", name="uk_md_bom_code"),
        table_comment("BOM 主表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bom_code: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_product.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(16), default="V1.0", nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="1启用 0停用")

    items: Mapped[list["MdBomItem"]] = relationship(lazy="noload")


class MdBomItem(Base, TimestampMixin):
    """BOM 明细（单位用量 + 损耗率），报工扣料的依据。"""

    __tablename__ = "md_bom_item"
    __table_args__ = (
        UniqueConstraint("bom_id", "material_id", name="uk_md_bom_item"),
        table_comment("BOM 明细表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("md_bom.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("mm_material.id"), nullable=False)
    qty_per_unit: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False,
                                                comment="单位产品用量")
    loss_rate: Mapped[float] = mapped_column(Numeric(8, 4), default=0.0, nullable=False,
                                             comment="损耗率，如 0.03 表示 3%")
    position: Mapped[str] = mapped_column(String(64), default="", nullable=False,
                                          comment="装配位号")


class MdRouting(Base, TimestampMixin):
    """工艺路线主表。"""

    __tablename__ = "md_routing"
    __table_args__ = (
        UniqueConstraint("routing_code", name="uk_md_routing_code"),
        table_comment("工艺路线主表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    routing_code: Mapped[str] = mapped_column(String(64), nullable=False)
    routing_name: Mapped[str] = mapped_column(String(128), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_product.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(16), default="V1.0", nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    operations: Mapped[list["MdRoutingOperation"]] = relationship(lazy="noload")


class MdRoutingOperation(Base, TimestampMixin):
    """工艺工序：工单工序拆分的模板来源，同时决定是否纳入 SPC 监控。"""

    __tablename__ = "md_routing_operation"
    __table_args__ = (
        UniqueConstraint("routing_id", "seq", name="uk_md_routing_op_seq"),
        table_comment("工艺工序表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    routing_id: Mapped[int] = mapped_column(ForeignKey("md_routing.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, comment="工序序号")
    operation_code: Mapped[str] = mapped_column(String(32), nullable=False)
    operation_name: Mapped[str] = mapped_column(String(64), nullable=False)
    default_equipment_id: Mapped[int | None] = mapped_column(ForeignKey("md_equipment.id"))
    std_time_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                              comment="标准工时（秒/件）")
    setup_time_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                                comment="换线准备工时（秒）")
    qc_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False,
                                              comment="该工序是否必须报检")
    # SPC 关键质量特性（CTQ）配置：控制图的核心参数来源
    spc_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    spc_feature_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    spc_nominal: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False,
                                               comment="目标值")
    spc_upper: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False,
                                             comment="规格上限 USL")
    spc_lower: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False,
                                             comment="规格下限 LSL")
    spc_subgroup_size: Mapped[int] = mapped_column(Integer, default=5, nullable=False,
                                                   comment="X̄-R 图子组容量")


# ------------------------------------------------------------------ 仓储伙伴
class MdWarehouse(Base, TimestampMixin):
    """仓库 / 库位（原料仓、线边库、成品仓）。"""

    __tablename__ = "md_warehouse"
    __table_args__ = (
        UniqueConstraint("code", name="uk_md_warehouse_code"),
        table_comment("仓库档案表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(16), default="RAW", nullable=False,
                                          comment="RAW原料/WIP线边/FG成品")
    workshop_id: Mapped[int | None] = mapped_column(ForeignKey("md_workshop.id"))


class MdSupplier(Base, TimestampMixin):
    """供应商。"""

    __tablename__ = "md_supplier"
    __table_args__ = (
        UniqueConstraint("code", name="uk_md_supplier_code"),
        table_comment("供应商档案表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    contact: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    qualification: Mapped[str] = mapped_column(String(32), default="A", nullable=False,
                                               comment="资质等级 A/B/C")
