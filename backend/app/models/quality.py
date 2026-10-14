"""质量管理模型（4 张表）+ SPC 判异准则枚举。

* ``qm_defect_type``  不良代码字典，柏拉图分析维度来源；
* ``qm_inspection_task`` 质检单（可由 SPC 超限告警自动生成）；
* ``qm_inspection_record`` 逐件检验记录；
* ``qm_spc_subgroup`` SPC 子组，保存原始样本值与计算结果。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import StrEnum, TimestampMixin, table_comment


class InspectionStatus(StrEnum):
    """质检单状态。"""

    PENDING = "PENDING"    # 待处理
    TESTING = "TESTING"    # 检验中
    PASSED = "PASSED"      # 合格
    FAILED = "FAILED"      # 不合格
    CLOSED = "CLOSED"      # 已关闭


class InspectionSource(StrEnum):
    """质检单来源：SPC 自动告警是本项目重点之一。"""

    SPC_ALERT = "SPC_ALERT"  # SPC 控制图超限自动生成
    MANUAL = "MANUAL"        # 人工抽检 / 报检
    INCOMING = "INCOMING"    # 来料检验


class QmDefectType(Base, TimestampMixin):
    """不良类型字典。"""

    __tablename__ = "qm_defect_type"
    __table_args__ = (
        UniqueConstraint("code", name="uk_qm_defect_code"),
        table_comment("不良类型字典表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="", nullable=False,
                                          comment="尺寸/外观/性能")
    severity: Mapped[str] = mapped_column(String(16), default="MINOR", nullable=False,
                                          comment="CRITICAL/MAJOR/MINOR")


class QmInspectionTask(Base, TimestampMixin):
    """质检单。SPC 触发的超限批次会在这里落地成「待处理」任务。"""

    __tablename__ = "qm_inspection_task"
    __table_args__ = (
        UniqueConstraint("task_no", name="uk_qm_task_no"),
        table_comment("质检单表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_no: Mapped[str] = mapped_column(String(64), nullable=False)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("pp_work_order.id"))
    operation_id: Mapped[int | None] = mapped_column(ForeignKey("pp_work_order_operation.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("md_product.id"))
    spc_subgroup_id: Mapped[int | None] = mapped_column(ForeignKey("qm_spc_subgroup.id"),
                                                        comment="触发的SPC子组")
    source: Mapped[str] = mapped_column(String(16), default=InspectionSource.MANUAL.value,
                                        nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=InspectionStatus.PENDING.value,
                                        nullable=False)
    sample_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                            comment="抽检数量")
    defect_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conclusion: Mapped[str] = mapped_column(String(500), default="", nullable=False,
                                            comment="结论描述")
    trigger_reason: Mapped[str] = mapped_column(String(500), default="", nullable=False,
                                                comment="生成原因（含判异准则）")
    inspector_no: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)


class QmInspectionRecord(Base, TimestampMixin):
    """检验记录：单件测量值 + 判定结果。"""

    __tablename__ = "qm_inspection_record"
    __table_args__ = table_comment("检验记录明细表")

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("qm_inspection_task.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, comment="样本序号")
    feature_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    measured_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, comment="实测值")
    nominal: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False)
    tolerance_upper: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False)
    tolerance_lower: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False)
    result: Mapped[str] = mapped_column(String(8), default="OK", nullable=False, comment="OK/NG")
    defect_type_id: Mapped[int | None] = mapped_column(ForeignKey("qm_defect_type.id"))
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class QmSpcSubgroup(Base, TimestampMixin):
    """SPC 子组（X̄-R 图的基本单位）。

    每次采集 n 个样本构成子组，同时算出：

    * 子组均值 X̄  = Σx / n
    * 子组极差 R   = max(x) - min(x)
    """

    __tablename__ = "qm_spc_subgroup"
    __table_args__ = (
        UniqueConstraint("product_id", "operation_code", "subgroup_no",
                         name="uk_qm_spc_subgroup"),
        table_comment("SPC 子组数据表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("pp_work_order.id"))
    operation_id: Mapped[int | None] = mapped_column(ForeignKey("pp_work_order_operation.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("md_product.id"), nullable=False)
    operation_code: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="受控质量特性")
    subgroup_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="子组序号")
    subgroup_size: Mapped[int] = mapped_column(Integer, default=5, nullable=False,
                                               comment="子组容量 n")
    sample_values: Mapped[str] = mapped_column(String(1000), nullable=False,
                                               comment="原始样本值JSON数组")
    mean_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, comment="子组均值 X̄")
    range_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, comment="子组极差 R")
    nominal: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False)
    upper_spec: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False)
    lower_spec: Mapped[float] = mapped_column(Numeric(18, 4), default=0.0, nullable=False)
    is_out_of_control: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False,
                                                    comment="是否触发判异")
    alarm_rules: Mapped[str] = mapped_column(String(255), default="", nullable=False,
                                             comment="命中的判异准则编号，逗号分隔")
    sample_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="取样时间")
