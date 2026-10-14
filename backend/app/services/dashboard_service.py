"""设备服务与车间看板聚合。

看板数据来源分工：

* **实时面**（秒级）：读 Redis / 数采网关快照，不查库；
* **业务面**（准实时）：工单进度、待处理质检、库存预警走 SQL 聚合。

两者在 :meth:`DashboardService.overview` 里合并成一次响应，
前端只需一次请求即可渲染整屏。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.equipment import EqAlarm, EqStatusLog, EqAlarm as Alarm
from app.models.inventory import MmInventoryStock, MmMaterial
from app.models.master import EquipmentStatus, MdEquipment
from app.models.order import PpWorkOrder, PpWorkReport, WorkOrderStatus
from app.models.quality import InspectionStatus, QmInspectionTask
from app.realtime.redis_client import get_cache
from app.services.order_service import OrderService
from app.utils import safe_pct


class EquipmentService:
    """设备台账与运行数据服务。"""

    def __init__(self, db: Session):
        self.db = db

    def list_equipment(self) -> list[dict]:
        """设备列表 + Redis 中的实时层信息。"""
        cache = get_cache()
        items = []
        for equip in self.db.execute(select(MdEquipment)).scalars().all():
            realtime = cache.read_device_status(equip.code) or {}
            items.append({
                "id": equip.id,
                "code": equip.code,
                "name": equip.name,
                "model": equip.model,
                "workshop_id": equip.workshop_id,
                "line_id": equip.line_id,
                "static_status": equip.status,
                "realtime": realtime,
                "status": realtime.get("status", equip.status),
                "load_rate": realtime.get("load_rate", 0),
                "temperature": realtime.get("temperature", 0),
                "total_output": realtime.get("total_output", 0),
                "current_order": realtime.get("work_order_no", ""),
            })
        return items

    def running_realtime(self) -> dict:
        """从缓存快照读取全部设备实时状态（用于 SSE 冷启动首帧）。"""
        return get_cache().read_dashboard_snapshot()

    def open_alarms(self, limit: int = 20) -> list[EqAlarm]:
        stmt = (
            select(EqAlarm)
            .where(EqAlarm.status != "CLOSED")
            .order_by(EqAlarm.id.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def alarm_summary(self) -> dict:
        rows = self.db.execute(
            select(EqAlarm.level, func.count(EqAlarm.id))
            .where(EqAlarm.status != "CLOSED")
            .group_by(EqAlarm.level)
        ).all()
        summary = {"total": 0}
        for level, count in rows:
            summary[level] = int(count)
            summary["total"] += int(count)
        return summary

    def utilization(self, *, since: datetime | None = None) -> dict:
        """统计窗口内的稼动率（以日志为准，与内存中响声密度无关）。"""
        since = since or (datetime.now() - timedelta(days=1))
        rows = self.db.execute(
            select(
                EqStatusLog.equipment_id,
                func.sum(EqStatusLog.run_seconds).label("run_sec"),
                func.count(EqStatusLog.id).label("samples"),
                func.sum(EqStatusLog.output_qty).label("output"),
            )
            .where(EqStatusLog.collected_at >= since)
            .group_by(EqStatusLog.equipment_id)
        ).all()
        window = max((datetime.now() - since).total_seconds(), 1)
        result = {}
        for row in rows:
            result[row.equipment_id] = {
                "run_seconds": int(row.run_sec or 0),
                "samples": int(row.samples or 0),
                "output": int(row.output or 0),
                "availability": safe_pct(int(row.run_sec or 0), window),
            }
        return result


class DashboardService:
    """车间看板聚合服务。"""

    def __init__(self, db: Session):
        self.db = db
        self.orders = OrderService(db)
        self.equipment = EquipmentService(db)

    def overview(self) -> dict:
        """一次性返回看板全量数据。"""
        cache = get_cache()
        snapshot = cache.read_dashboard_snapshot()
        realtime = snapshot.get("devices") or []
        last_device = sorted(realtime, key=lambda x: x.get("collected_at", ""),
                             reverse=True)[:8]

        progress = self.orders.progress_matrix()
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_rows = self.db.execute(
            select(
                func.coalesce(func.sum(PpWorkReport.qty_good), 0),
                func.coalesce(func.sum(PpWorkReport.qty_defect), 0),
            ).where(PpWorkReport.report_time >= today_start)
        ).first()
        today_good = int(today_rows[0] or 0) if today_rows else 0
        today_defect = int(today_rows[1] or 0) if today_rows else 0

        pending_qc = self.db.execute(
            select(func.count(QmInspectionTask.id)).where(
                QmInspectionTask.status == InspectionStatus.PENDING.value
            )
        ).scalar_one()

        low_stock = self._low_stock_items()
        recent_alarms = self.equipment.open_alarms(limit=5)

        return {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cache_backend": cache.backend_name,
            "gateway_enabled": settings.GATEWAY_ENABLED,
            "orders": progress,
            "today": {
                "qty_good": today_good,
                "qty_defect": today_defect,
                "yield_rate": safe_pct(today_good, today_good + today_defect),
            },
            "devices": {
                "summary": snapshot.get("devices") and self._device_summary(realtime) or {
                    "total": self.db.execute(
                        select(func.count(MdEquipment.id))).scalar_one(),
                    "running": 0, "idle": 0, "fault": 0, "maintain": 0,
                    "utilization": 0.0,
                },
                "latest": last_device,
            },
            "quality": {
                "pending_tasks": int(pending_qc or 0),
                "recent_alarms": [{
                    "alarm_no": a.alarm_no,
                    "equipment_id": a.equipment_id,
                    "alarm_type": a.alarm_type,
                    "level": a.level,
                    "message": a.message,
                    "occurred_at": a.occurred_at,
                } for a in recent_alarms],
            },
            "inventory": {
                "low_stock_count": len(low_stock),
                "low_stock_items": low_stock[:5],
            },
        }

    @staticmethod
    def _device_summary(devices: list[dict]) -> dict:
        running = [d for d in devices if d.get("status") == EquipmentStatus.RUN.value]
        total = len(devices)
        return {
            "total": total,
            "running": len(running),
            "idle": sum(1 for d in devices
                        if d.get("status") == EquipmentStatus.IDLE.value),
            "fault": sum(1 for d in devices
                         if d.get("status") == EquipmentStatus.FAULT.value),
            "maintain": sum(1 for d in devices
                            if d.get("status") == EquipmentStatus.MAINTAIN.value),
            "utilization": safe_pct(len(running), total),
        }

    def _low_stock_items(self) -> list[dict]:
        rows = self.db.execute(
            select(
                MmMaterial.code, MmMaterial.name, MmMaterial.unit,
                MmMaterial.safety_stock,
                func.sum(MmInventoryStock.qty_on_hand).label("on_hand"),
            )
            .join(MmInventoryStock, MmInventoryStock.material_id == MmMaterial.id)
            .group_by(MmMaterial.id, MmMaterial.code, MmMaterial.name,
                      MmMaterial.unit, MmMaterial.safety_stock)
        ).all()
        items = []
        for row in rows:
            on_hand = float(row.on_hand or 0)
            safety = float(row.safety_stock or 0)
            if on_hand < safety:
                items.append({
                    "material_code": row.code,
                    "material_name": row.name,
                    "unit": row.unit,
                    "on_hand": round(on_hand, 3),
                    "safety_stock": safety,
                    "gap": round(safety - on_hand, 3),
                })
        return sorted(items, key=lambda x: x["gap"], reverse=True)

    def recent_reports(self, limit: int = 8) -> list[dict]:
        """最近报工流水（看板滚动区域）。"""
        rows = self.db.execute(
            select(PpWorkReport).order_by(PpWorkReport.id.desc()).limit(limit)
        ).scalars().all()
        result = []
        for row in rows:
            order = self.db.get(PpWorkOrder, row.work_order_id)
            result.append({
                "report_no": row.report_no,
                "order_no": order.order_no if order else "",
                "qty_good": row.qty_good,
                "qty_defect": row.qty_defect,
                "report_time": row.report_time,
            })
        return result

    def status_distribution(self) -> list[dict]:
        """工单状态分布，直接喂给 ECharts 饼图。"""
        rows = self.db.execute(
            select(PpWorkOrder.status, func.count(PpWorkOrder.id))
            .group_by(PpWorkOrder.status)
        ).all()
        labels = {
            WorkOrderStatus.DRAFT.value: "草稿",
            WorkOrderStatus.RELEASED.value: "已下达",
            WorkOrderStatus.IN_PROGRESS.value: "生产中",
            WorkOrderStatus.PAUSED.value: "暂停",
            WorkOrderStatus.COMPLETED.value: "已完工",
            WorkOrderStatus.CANCELLED.value: "已作废",
        }
        return [{"name": labels.get(status, status), "value": int(count)}
                for status, count in rows]
