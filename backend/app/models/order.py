"""生产工单模型（4 张表）+ 工单状态机定义。

``pp_work_order`` 是主表，``pp_work_order_operation`` 按工艺路线把工单拆成工序，
``pp_work_report`` 是每次工序报工的明细凭证（幂等键唯一约束落在这一层），
``pp_material_requirement`` 记录工单的物料需求与实际领用量。

状态机见 :class:`WorkOrderStatus`，所有流转集中在
``app/services/order_service.py`` 中校验，避免状态被任意接口直接改写。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import StrEnum, TimestampMixin, table_comment


class WorkOrderStatus(StrEnum):
    """工单状态。

    流转路径::

        DRAFT ──下达──> RELEASED ──开工──> IN_PROGRESS ──完工──> COMPLETED
          │                │                   │
          └──作废──> CANCELLED <────作废────────┘        ┌──> PAUSED <─┐
                                                        └──恢复───────┘

    流转表放在类外的 :data:`WORK_ORDER_TRANSITIONS`：本类继承了 ``str`` mixin，
    若把 dict 写在类体内会被 Python 当成枚举成员，导致属性访问异常。
    """

    DRAFT = "DRAFT"              # 草稿
    RELEASED = "RELEASED"        # 已下达（已审核，可开工）
    IN_PROGRESS = "IN_PROGRESS"  # 生产中
    PAUSED = "PAUSED"            # 暂停（设备 / 质量原因）
    COMPLETED = "COMPLETED"      # 已完工
    CANCELLED = "CANCELLED"      # 已作废

    @property
    def is_terminal(self) -> bool:
        """是否为终态（不可再流转）。"""
        return not WORK_ORDER_TRANSITIONS[self.value]

    def can_transition_to(self, target: "WorkOrderStatus | str") -> bool:
        """判断是否允许流转到目标状态。"""
        to = target.value if isinstance(target, WorkOrderStatus) else target
        return to in WORK_ORDER_TRANSITIONS.get(self.value, set())


#: 合法流转表：状态机的唯一真源
WORK_ORDER_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"RELEASED", "CANCELLED"},
    "RELEASED": {"IN_PROGRESS", "PAUSED", "CANCELLED"},
    "IN_PROGRESS": {"PAUSED", "COMPLETED", "CANCELLED"},
    "PAUSED": {"IN_PROGRESS", "CANCELLED"},
    "COMPLETED": set(),       # 终态
    "CANCELLED": set(),       # 终态
}


def allowed_order_targets(source: str) -> list[str]:
    """返回某状态的全部合法目标状态，供接口文档与前端按钮渲染使用。"""
    return sorted(WORK_ORDER_TRANSITIONS.get(source, set()))


class OperationStatus(StrEnum):
    """工单工序状态。"""

    NOT_STARTED = "NOT_STARTED"  # 未开工
    RUNNING = "RUNNING"          # 加工中
    FINISHED = "FINISHED"        # 已完成


class PpWorkOrder(Base, TimestampMixin):
    """生产工单。"""

    __tablename__ = "pp_work_order"
    __table_args__ = (
        UniqueConstraint("order_no", name="uk_pp_work_order_no"),
        table_comment("生产工单表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="工单号")
    product_id: Mapped[int] = mapped_column(ForeignKey("md_product.id"), nullable=False)
    routing_id: Mapped[int] = mapped_column(ForeignKey("md_routing.id"), nullable=False)
    bom_id: Mapped[int | None] = mapped_column(ForeignKey("md_bom.id"))
    workshop_id: Mapped[int | None] = mapped_column(ForeignKey("md_workshop.id"))
    line_id: Mapped[int | None] = mapped_column(ForeignKey("md_production_line.id"))

    qty_planned: Mapped[int] = mapped_column(Integer, nullable=False, comment="计划产量")
    qty_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                               comment="累计完成量")
    qty_good: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="合格品数量")
    qty_defect: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                            comment="不良品数量")
    scrap_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="报废数量")

    status: Mapped[str] = mapped_column(String(16), default=WorkOrderStatus.DRAFT.value,
                                        nullable=False, comment="工单状态")
    priority: Mapped[int] = mapped_column(Integer, default=5, nullable=False,
                                          comment="优先级 1(最高)-9(最低)")
    plan_start: Mapped[datetime | None] = mapped_column(DateTime)
    plan_end: Mapped[datetime | None] = mapped_column(DateTime)
    actual_start: Mapped[datetime | None] = mapped_column(DateTime)
    actual_end: Mapped[datetime | None] = mapped_column(DateTime)
    released_by: Mapped[str] = mapped_column(String(32), default="", nullable=False,
                                             comment="下达人账号")
    owner_group: Mapped[str] = mapped_column(String(32), default="", nullable=False,
                                             comment="责任班组")
    source: Mapped[str] = mapped_column(String(16), default="MANUAL", nullable=False,
                                        comment="MANUAL手工 / IMPORT导入 / API接口")
    # 合并戳字段是「谁最后改了数量」的凭证，用于报工并发场景排查
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                         comment="乐观锁版本号")

    @property
    def progress(self) -> float:
        """工单进度百分比，保留一位小数。"""
        if not self.qty_planned:
            return 0.0
        return round(float(self.qty_completed) / float(self.qty_planned) * 100, 1)

    @property
    def yield_rate(self) -> float:
        """良品率百分比。"""
        if not self.qty_completed:
            return 0.0
        return round(float(self.qty_good) / float(self.qty_completed) * 100, 1)


class PpWorkOrderOperation(Base, TimestampMixin):
    """工单工序：报工、质检的最小业务单元。"""

    __tablename__ = "pp_work_order_operation"
    __table_args__ = (
        UniqueConstraint("work_order_id", "seq", name="uk_pp_wo_op_seq"),
        table_comment("工单工序表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("pp_work_order.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_code: Mapped[str] = mapped_column(String(32), nullable=False)
    operation_name: Mapped[str] = mapped_column(String(64), nullable=False)
    routing_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey("md_routing_operation.id"), comment="来源工艺工序"
    )
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("md_equipment.id"))
    plan_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    done_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    good_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defect_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    std_time_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_labor_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                                  comment="实际人工秒")
    actual_machine_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                                    comment="实际机器秒")
    status: Mapped[str] = mapped_column(String(16), default=OperationStatus.NOT_STARTED.value,
                                        nullable=False)
    qc_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    spc_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    @property
    def progress(self) -> float:
        if not self.plan_qty:
            return 0.0
        return round(float(self.done_qty) / float(self.plan_qty) * 100, 1)


class PpWorkReport(Base, TimestampMixin):
    """工序报工记录。

    ``idempotency_key`` 上的 **唯一约束** 是防止重复报工的最后一道防线：
    即便应用层幂等逻辑被绕过（并发、脚本重放），数据库也会直接拒绝第二笔插入。
    """

    __tablename__ = "pp_work_report"
    __table_args__ = (
        UniqueConstraint("report_no", name="uk_pp_report_no"),
        UniqueConstraint("idempotency_key", name="uk_pp_report_idempotency"),
        table_comment("工序报工记录表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="报工单号")
    work_order_id: Mapped[int] = mapped_column(ForeignKey("pp_work_order.id"), nullable=False)
    operation_id: Mapped[int] = mapped_column(ForeignKey("pp_work_order_operation.id"),
                                              nullable=False)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("md_employee.id"))
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("md_equipment.id"))
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("md_shift.id"))
    qty_good: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    qty_defect: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    labor_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    machine_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="报工时间")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="幂等键")
    # 一次报工可能触发多条库存流水，用 JSON 明细记录便于追溯
    inventory_flows: Mapped[str] = mapped_column(String(2000), default="[]", nullable=False,
                                                 comment="本次报工产生的库存流水JSON")


class PpMaterialRequirement(Base, TimestampMixin):
    """工单物料需求 / 领用台账。"""

    __tablename__ = "pp_material_requirement"
    __table_args__ = (
        UniqueConstraint("work_order_id", "material_id", name="uk_pp_mr"),
        table_comment("工单物料需求表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("pp_work_order.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("mm_material.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("md_warehouse.id"), nullable=False)
    qty_required: Mapped[float] = mapped_column(Numeric(18, 3), default=0.0, nullable=False,
                                                comment="计划需求量")
    qty_issued: Mapped[float] = mapped_column(Numeric(18, 3), default=0.0, nullable=False,
                                              comment="累计已发量")
    qty_returned: Mapped[float] = mapped_column(Numeric(18, 3), default=0.0, nullable=False,
                                                comment="累计退料量")
    unit_usage: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False,
                                              comment="单位用量（含损耗）")
