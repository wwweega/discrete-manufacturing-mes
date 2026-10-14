"""设备数采网关（模拟器）。

对应简历「设备数据采集」：模拟 PLC / 数采盒子按固定周期上报运行数据。

设计说明
--------
* 网关**读取真实的业务状态**来生成数据：只有存在「加工中工序」的设备才上报 RUN，
  其余上报 IDLE；并以工单号为上下文，使产出数据能回流到工单进度；
* 每条数据同时做两件事：落 ``eq_status_log``（时序留痕，供稼动率统计），
  写 Redis（供看板秒级读取），再向 SSE 广播一帧；
* 周期性随机事件（温升告警、通信中断）模拟真实车间的异常，便于演示告警链路。
  随机数发生器使用固定种子，保证同一批次演示可复现。
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.equipment import EqAlarm, EqStatusLog
from app.models.master import EquipmentStatus, MdEquipment
from app.models.order import OperationStatus, PpWorkOrder, PpWorkOrderOperation
from app.realtime.redis_client import get_cache
from app.realtime.sse_hub import hub
from app.utils import next_no

_RandomT = random.Random


class DeviceGateway:
    """设备数采网关。"""

    def __init__(self, *, interval_sec: int | None = None, seed: int = 20260801,
                 write_db: bool = True, engine=None):
        self.interval = interval_sec or settings.GATEWAY_INTERVAL_SEC
        self.write_db = write_db
        self._seed = seed
        self._rng = _RandomT(seed)
        self._task: asyncio.Task | None = None
        self._running = False
        self._seq = 0
        self._engine = engine
        self._session_factory = (
            sessionmaker(bind=engine, expire_on_commit=False) if engine else None
        )
        # 每台设备的累计产出，模拟网关侧计数器的连续性
        self._counters: dict[int, int] = {}

    # ---------------------------------------------------------------- 生命周期
    async def start(self) -> None:
        """启动后台循环（幂等）。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="device-gateway")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._running = False

    async def _loop(self) -> None:  # pragma: no cover - 常驻协程
        while self._running:
            try:
                self.tick()
            except Exception:  # 单次采集失败不影响后续周期
                pass
            await asyncio.sleep(self.interval)

    # ---------------------------------------------------------------- 采集
    def tick(self) -> dict:
        """执行一次全量采集，返回本帧快照。"""
        self._seq += 1
        devices: list[dict[str, Any]] = []
        alarms: list[dict[str, Any]] = []

        db = self._new_session()
        try:
            equipment_rows = list(db.execute(select(MdEquipment)).scalars().all())
            active_ops = self._load_active_operations(db)
            op_map = {op["equipment_id"]: op for op in active_ops if op["equipment_id"]}

            for equip in equipment_rows:
                snapshot = self._sample_one(equip, op_map.get(equip.id))
                devices.append(snapshot)
                if self.write_db:
                    self._persist_log(db, snapshot)
                if snapshot["alarm_message"]:
                    alarms.append({
                        "equipment_code": snapshot["equipment_code"],
                        "alarm_type": snapshot["alarm_type"],
                        "message": snapshot["alarm_message"],
                        "level": snapshot["alarm_level"],
                    })
                    if self.write_db:
                        self._persist_alarm(db, snapshot)
            if self.write_db:
                db.commit()
        finally:
            db.close()

        cache = get_cache()
        cache.write_device_snapshot(devices)
        frame = self.build_frame(devices, alarms)
        cache.publish_device_event(frame)
        hub.publish("dashboard", frame)
        return frame

    # ---------------------------------------------------------------- 采样算法
    def _load_active_operations(self, db: Session) -> list[dict[str, Any]]:
        stmt = (
            select(
                PpWorkOrderOperation.id,
                PpWorkOrderOperation.equipment_id,
                PpWorkOrderOperation.operation_name,
                PpWorkOrderOperation.plan_qty,
                PpWorkOrderOperation.done_qty,
                PpWorkOrder.order_no,
                PpWorkOrder.product_id,
            )
            .join(PpWorkOrder, PpWorkOrder.id == PpWorkOrderOperation.work_order_id)
            .where(PpWorkOrderOperation.status == OperationStatus.RUNNING.value)
        )
        rows = db.execute(stmt).all()
        return [{
            "operation_id": r[0], "equipment_id": r[1], "operation_name": r[2],
            "plan_qty": r[3], "done_qty": r[4], "order_no": r[5], "product_id": r[6],
        } for r in rows]

    def _sample_one(self, equip: MdEquipment, active_op: dict | None) -> dict[str, Any]:
        """对单台设备生成一帧运行数据。"""
        rng = self._rng
        rated_output = int(equip.rated_output or 0)
        rated_speed = int(equip.rated_speed or 0)

        if active_op:
            status = EquipmentStatus.RUN.value
            # 实际产出围绕额定产能小幅波动，叠加偶发的降速
            ratio = rng.uniform(0.82, 1.05)
            output = max(int(rated_output * ratio / max(self.interval, 1) or 1), 1)
            load_rate = round(rng.uniform(55, 92), 2)
            spindle = round(rated_speed * rng.uniform(0.9, 1.0), 2)
            feed = round(rng.uniform(120, 260), 2)
            temperature = round(rng.uniform(38, 58), 2)
        else:
            status = EquipmentStatus.IDLE.value
            output, load_rate, spindle, feed = 0, round(rng.uniform(0, 6), 2), 0, 0
            temperature = round(rng.uniform(22, 32), 2)

        alarm_type = alarm_message = ""
        alarm_level = ""
        # 偶发异常： RUN 2.5% 概率温升告警， 1.5% 概率通信中断
        if status == EquipmentStatus.RUN.value and rng.random() < 0.025:
            temperature = round(rng.uniform(72, 88), 2)
            alarm_type, alarm_level = "OVER_TEMP", "MAJOR"
            alarm_message = f"主轴温度异常升高至 {temperature}℃"
        elif rng.random() < 0.015:
            status = EquipmentStatus.FAULT.value
            output = 0
            alarm_type, alarm_level = "COM_LOST", "CRITICAL"
            alarm_message = "设备通信中断，等待现场确认"

        total_output = self._counters.get(equip.id, 0) + output
        self._counters[equip.id] = total_output

        return {
            "equipment_id": equip.id,
            "equipment_code": equip.code,
            "equipment_name": equip.name,
            "workshop_id": equip.workshop_id,
            "status": status,
            "spindle_speed": spindle,
            "feed_rate": feed,
            "load_rate": load_rate,
            "temperature": temperature,
            "output_qty": output,
            "total_output": total_output,
            "run_seconds": self.interval if status == EquipmentStatus.RUN.value else 0,
            "work_order_no": active_op["order_no"] if active_op else "",
            "operation_name": active_op["operation_name"] if active_op else "",
            "plan_qty": active_op["plan_qty"] if active_op else 0,
            "done_qty": active_op["done_qty"] if active_op else 0,
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "gateway_seq": self._seq,
            "alarm_type": alarm_type,
            "alarm_level": alarm_level,
            "alarm_message": alarm_message,
        }

    # ---------------------------------------------------------------- 落库
    def _persist_log(self, db: Session, snapshot: dict) -> None:
        log = EqStatusLog(
            equipment_id=snapshot["equipment_id"],
            workshop_id=snapshot["workshop_id"],
            status=snapshot["status"],
            spindle_speed=snapshot["spindle_speed"],
            feed_rate=snapshot["feed_rate"],
            load_rate=snapshot["load_rate"],
            temperature=snapshot["temperature"],
            output_qty=snapshot["output_qty"],
            total_output=snapshot["total_output"],
            run_seconds=snapshot["run_seconds"],
            collected_at=datetime.now(),
            gateway_seq=snapshot["gateway_seq"],
        )
        db.add(log)

    def _persist_alarm(self, db: Session, snapshot: dict) -> None:
        alarm = EqAlarm(
            alarm_no=next_no("AL"),
            equipment_id=snapshot["equipment_id"],
            alarm_type=snapshot["alarm_type"],
            level=snapshot["alarm_level"],
            message=snapshot["alarm_message"],
            occurred_at=datetime.now(),
            status="OPEN",
        )
        db.add(alarm)

    # ---------------------------------------------------------------- 其他
    def _new_session(self) -> Session:
        """网关使用独立会话，避免与请求共享事务。"""
        if self._session_factory is not None:
            return self._session_factory()
        from app.db.session import SessionLocal

        return SessionLocal()

    @staticmethod
    def build_frame(devices: list[dict], alarms: list[dict]) -> dict:
        """组装 SSE 数据帧（看板所需的最小数据面）。"""
        running = [d for d in devices if d["status"] == EquipmentStatus.RUN.value]
        return {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": {
                "total": len(devices),
                "running": len(running),
                "idle": sum(1 for d in devices if d["status"] == EquipmentStatus.IDLE.value),
                "fault": sum(1 for d in devices if d["status"] == EquipmentStatus.FAULT.value),
                "maintain": sum(1 for d in devices
                                if d["status"] == EquipmentStatus.MAINTAIN.value),
                "utilization": round(len(running) / len(devices) * 100, 2) if devices else 0.0,
                "total_output": sum(d["total_output"] for d in devices),
            },
            "devices": devices,
            "alarms": alarms[-10:],
        }
