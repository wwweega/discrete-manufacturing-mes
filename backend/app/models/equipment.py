"""设备运行模型（2 张表）。

``eq_status_log``  数采网关上报的时序运行数据，写库留痕 —— 用于稼动率统计；
``eq_alarm``        设备告警台账 —— 用于看板告警区与维保跟踪。

实时状态本身不落这两张表以外的账号 bit，而是写入 Redis（见 app/realtime/），
保证看板读取是 O(1) 的内存访问而不是全表扫描。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin, table_comment


class EqStatusLog(Base, TimestampMixin):
    """设备运行状态时序日志（数采网关写入）。"""

    __tablename__ = "eq_status_log"
    __table_args__ = table_comment("设备运行状态日志表")

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("md_equipment.id"), nullable=False)
    workshop_id: Mapped[int | None] = mapped_column(ForeignKey("md_workshop.id"))
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("pp_work_order.id"),
                                                      comment="当前加工工单")
    status: Mapped[str] = mapped_column(String(16), nullable=False, comment="RUN/IDLE/FAULT/...")
    spindle_speed: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False,
                                                 comment="主轴转速")
    feed_rate: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False,
                                             comment="进给速度")
    load_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0.0, nullable=False,
                                             comment="负载率%")
    temperature: Mapped[float] = mapped_column(Numeric(6, 2), default=0.0, nullable=False,
                                               comment="温度℃")
    output_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                            comment="本周期产出")
    total_output: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                              comment="当班累计产出")
    run_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                             comment="本周期运行秒")
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="采集时间")
    gateway_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                             comment="网关上报序号，用于去重")


class EqAlarm(Base, TimestampMixin):
    """设备告警台账。"""

    __tablename__ = "eq_alarm"
    __table_args__ = (
        UniqueConstraint("alarm_no", name="uk_eq_alarm_no"),
        table_comment("设备告警表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alarm_no: Mapped[str] = mapped_column(String(64), nullable=False)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("md_equipment.id"), nullable=False)
    alarm_type: Mapped[str] = mapped_column(String(32), nullable=False,
                                            comment="OVER_TEMP/LOAD_HIGH/COM_LOST")
    level: Mapped[str] = mapped_column(String(16), default="MINOR", nullable=False,
                                       comment="CRITICAL/MAJOR/MINOR")
    message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", nullable=False,
                                        comment="OPEN/PROCESSING/CLOSED")
    handler: Mapped[str] = mapped_column(String(32), default="", nullable=False)
