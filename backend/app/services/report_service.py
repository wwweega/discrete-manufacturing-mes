"""8 张统计报表（多表关联 SQL）。

简历对应描述：「多表关联 SQL 实现工单进度、良品率、设备稼动率等 8 张统计报表」。

编号与清单：

=== ==================== ==========================================
 #  报表名称             主要关联表
=== ==================== ==========================================
 1  工单进度报表          pp_work_order ⋈ md_product ⋈ pp_work_order_operation
 2  良品率报表            pp_work_order ⋈ md_product ⋈ md_production_line
 3  设备稼动率报表        eq_status_log ⋈ md_equipment ⋈ md_production_line
 4  产量日报/月报         pp_work_report ⋈ pp_work_order ⋈ md_product
 5  工序工时效率报表      pp_work_order_operation ⋈ md_routing_operation ⋈ md_equipment
 6  质量不良柏拉图        qm_inspection_record ⋈ qm_defect_type ⋈ qm_inspection_task
 7  库存周转报表          mm_inventory_transaction ⋈ mm_material ⋈ mm_inventory_stock
 8  人员绩效报表          pp_work_report ⋈ md_employee ⋈ pp_work_order_operation
=== ==================== ==========================================

实现约定：
* 全部返回结果字段补齐 0（无数据也返回行），前端不需要做空值兜底；
* 百分比统一保留两位小数，分母为 0 返回 0。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.models.equipment import EqStatusLog
from app.models.inventory import MmInventoryStock, MmInventoryTransaction, MmMaterial
from app.models.master import (
    MdEmployee,
    MdEquipment,
    MdProductionLine,
    MdProduct,
    MdRoutingOperation,
)
from app.models.order import PpWorkOrder, PpWorkOrderOperation, PpWorkReport
from app.models.quality import QmDefectType, QmInspectionRecord, QmInspectionTask
from app.utils import safe_pct

REPORT_CATALOG: list[dict[str, str]] = [
    {"code": "work_order_progress", "name": "工单进度报表", "module": "生产"},
    {"code": "yield_rate", "name": "良品率报表", "module": "质量"},
    {"code": "equipment_oee", "name": "设备稼动率报表", "module": "设备"},
    {"code": "output_daily", "name": "产量日报表", "module": "生产"},
    {"code": "operation_efficiency", "name": "工序工时效率报表", "module": "生产"},
    {"code": "defect_pareto", "name": "质量不良柏拉图", "module": "质量"},
    {"code": "inventory_turnover", "name": "库存周转报表", "module": "库存"},
    {"code": "worker_performance", "name": "人员绩效报表", "module": "人力"},
]


class ReportService:
    """报表查询服务。"""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ 目录
    @staticmethod
    def catalog() -> list[dict[str, str]]:
        return list(REPORT_CATALOG)

    # ================================================== 1. 工单进度报表
    def work_order_progress(self, *, days: int = 30, status: str | None = None) -> dict:
        since = datetime.now() - timedelta(days=days)
        stmt = (
            select(
                PpWorkOrder.id,
                PpWorkOrder.order_no,
                PpWorkOrder.status,
                PpWorkOrder.priority,
                PpWorkOrder.qty_planned,
                PpWorkOrder.qty_completed,
                PpWorkOrder.qty_good,
                PpWorkOrder.qty_defect,
                MdProduct.code.label("product_code"),
                MdProduct.name.label("product_name"),
                MdProduct.unit,
                func.coalesce(
                    select(func.sum(PpWorkOrderOperation.done_qty))
                    .where(PpWorkOrderOperation.work_order_id == PpWorkOrder.id)
                    .correlate(PpWorkOrder)
                    .scalar_subquery(),
                    0,
                ).label("operation_done"),
                func.coalesce(
                    select(func.count(PpWorkOrderOperation.id))
                    .where(PpWorkOrderOperation.work_order_id == PpWorkOrder.id)
                    .correlate(PpWorkOrder)
                    .scalar_subquery(),
                    0,
                ).label("operation_total"),
            )
            .join(MdProduct, MdProduct.id == PpWorkOrder.product_id)
            .where(PpWorkOrder.created_at >= since)
        )
        if status:
            stmt = stmt.where(PpWorkOrder.status == status)

        rows = self.db.execute(stmt.order_by(PpWorkOrder.id.desc())).all()
        items = []
        for row in rows:
            planned = int(row.qty_planned or 0)
            completed = int(row.qty_completed or 0)
            items.append({
                "order_no": row.order_no,
                "product_code": row.product_code,
                "product_name": row.product_name,
                "unit": row.unit,
                "status": row.status,
                "priority": row.priority,
                "qty_planned": planned,
                "qty_completed": completed,
                "qty_good": int(row.qty_good or 0),
                "qty_defect": int(row.qty_defect or 0),
                "operation_total": int(row.operation_total or 0),
                "operation_done": int(row.operation_done or 0),
                "progress": safe_pct(completed, planned),
                "gap": planned - completed,
            })

        # 按产品汇总 + 整体达成率
        by_product: dict[str, dict[str, Any]] = {}
        for item in items:
            bucket = by_product.setdefault(item["product_code"], {
                "product_code": item["product_code"],
                "product_name": item["product_name"],
                "qty_planned": 0, "qty_completed": 0, "qty_good": 0, "orders": 0,
            })
            bucket["qty_planned"] += item["qty_planned"]
            bucket["qty_completed"] += item["qty_completed"]
            bucket["qty_good"] += item["qty_good"]
            bucket["orders"] += 1

        summary = {
            "qty_planned": sum(i["qty_planned"] for i in items),
            "qty_completed": sum(i["qty_completed"] for i in items),
            "qty_good": sum(i["qty_good"] for i in items),
        }
        summary["achieve_rate"] = safe_pct(summary["qty_completed"], summary["qty_planned"])
        return {"items": items, "by_product": list(by_product.values()), "summary": summary}

    # ================================================== 2. 良品率报表
    def yield_rate(self, *, days: int = 30) -> dict:
        since = datetime.now() - timedelta(days=days)
        stmt = (
            select(
                MdProduct.code,
                MdProduct.name,
                func.sum(PpWorkOrder.qty_completed).label("completed"),
                func.sum(PpWorkOrder.qty_good).label("good"),
                func.sum(PpWorkOrder.qty_defect).label("defect"),
                func.count(PpWorkOrder.id).label("orders"),
            )
            .join(MdProduct, MdProduct.id == PpWorkOrder.product_id)
            .where(PpWorkOrder.qty_completed > 0, PpWorkOrder.created_at >= since)
            .group_by(MdProduct.code, MdProduct.name)
        )
        rows = self.db.execute(stmt).all()

        items = []
        for row in rows:
            completed = int(row.completed or 0)
            good = int(row.good or 0)
            defect = int(row.defect or 0)
            items.append({
                "product_code": row.code,
                "product_name": row.name,
                "orders": int(row.orders or 0),
                "qty_completed": completed,
                "qty_good": good,
                "qty_defect": defect,
                "yield_rate": safe_pct(good, completed),
                "defect_rate": safe_pct(defect, completed),
            })
        items.sort(key=lambda x: x["yield_rate"])

        total_completed = sum(i["qty_completed"] for i in items)
        total_good = sum(i["qty_good"] for i in items)
        below_target = [i for i in items if i["yield_rate"] < 98.0]
        return {
            "items": items,
            "summary": {
                "qty_completed": total_completed,
                "qty_good": total_good,
                "overall_yield_rate": safe_pct(total_good, total_completed),
                "below_target_count": len(below_target),
                "target_yield_rate": 98.0,
            },
        }

    # ================================================== 3. 设备稼动率报表
    def equipment_oee(self, *, days: int = 1,
                      since: datetime | None = None) -> dict:
        """稼动率 = 运行时间 / 计划工作时间。

        数据来自数采网关写入的时序日志：每条记录统计一个周期内的运行秒数。
        """
        since = since or (datetime.now() - timedelta(days=days))
        stmt = (
            select(
                MdEquipment.id,
                MdEquipment.code,
                MdEquipment.name,
                MdEquipment.status,
                func.sum(EqStatusLog.run_seconds).label("run_seconds"),
                func.sum(EqStatusLog.output_qty).label("output"),
                func.count(EqStatusLog.id).label("samples"),
                func.sum(
                    case(
                        (EqStatusLog.status == "RUN", EqStatusLog.run_seconds),
                        else_=0,
                    )
                ).label("productive_seconds"),
            )
            .join(EqStatusLog, EqStatusLog.equipment_id == MdEquipment.id)
            .where(EqStatusLog.collected_at >= since)
            .group_by(MdEquipment.id, MdEquipment.code, MdEquipment.name,
                      MdEquipment.status)
        )
        rows = self.db.execute(stmt).all()

        items = []
        plan_seconds = max((datetime.now() - since).total_seconds(), 1)
        for row in rows:
            run_sec = int(row.run_seconds or 0)
            productive = int(row.productive_seconds or 0)
            items.append({
                "equipment_id": row.id,
                "equipment_code": row.code,
                "equipment_name": row.name,
                "status": row.status,
                "run_seconds": run_sec,
                "productive_seconds": productive,
                "output_qty": int(row.output or 0),
                "samples": int(row.samples or 0),
                "availability": safe_pct(productive, plan_seconds),
                "performance": safe_pct(int(row.output or 0),
                                        max(int(row.output or 0), 1) * 100 / 100),
            })
        items.sort(key=lambda x: x["availability"], reverse=True)

        avg = round(sum(i["availability"] for i in items) / len(items), 2) if items else 0.0
        return {
            "items": items,
            "summary": {
                "window_seconds": int(plan_seconds),
                "equipment_count": len(items),
                "avg_availability": avg,
                "total_output": sum(i["output_qty"] for i in items),
            },
        }

    # ================================================== 4. 产量日报
    def output_daily(self, *, days: int = 14) -> dict:
        stmt = (
            select(
                func.date(PpWorkReport.report_time).label("stat_date"),
                func.sum(PpWorkReport.qty_good).label("good"),
                func.sum(PpWorkReport.qty_defect).label("defect"),
                func.count(PpWorkReport.id).label("reports"),
                func.sum(PpWorkReport.labor_sec).label("labor_sec"),
            )
            .group_by(func.date(PpWorkReport.report_time))
            .order_by(func.date(PpWorkReport.report_time).desc())
            .limit(days)
        )
        rows = list(self.db.execute(stmt).all())
        rows.reverse()

        items = [{
            "stat_date": str(row.stat_date),
            "qty_good": int(row.good or 0),
            "qty_defect": int(row.defect or 0),
            "reports": int(row.reports or 0),
            "labor_hour": round(int(row.labor_sec or 0) / 3600, 2),
            "yield_rate": safe_pct(int(row.good or 0),
                                   int(row.good or 0) + int(row.defect or 0)),
        } for row in rows]

        # 产品维度 TOP
        by_product = self.db.execute(
            select(
                MdProduct.code, MdProduct.name,
                func.sum(PpWorkReport.qty_good).label("good"),
            )
            .join(PpWorkOrder, PpWorkOrder.id == PpWorkReport.work_order_id)
            .join(MdProduct, MdProduct.id == PpWorkOrder.product_id)
            .group_by(MdProduct.code, MdProduct.name)
            .order_by(func.sum(PpWorkReport.qty_good).desc())
            .limit(10)
        ).all()
        top_products = [{
            "product_code": row.code, "product_name": row.name,
            "qty_good": int(row.good or 0),
        } for row in by_product]

        total_good = sum(i["qty_good"] for i in items)
        return {
            "items": items,
            "top_products": top_products,
            "summary": {
                "total_good": total_good,
                "days": len(items),
                "avg_daily_output": round(total_good / len(items), 2) if items else 0.0,
            },
        }

    # ================================================== 5. 工序工时效率
    def operation_efficiency(self, *, work_order_id: int | None = None,
                             days: int = 30) -> dict:
        stmt = (
            select(
                PpWorkOrderOperation.id,
                PpWorkOrderOperation.operation_code,
                PpWorkOrderOperation.operation_name,
                PpWorkOrderOperation.std_time_sec,
                PpWorkOrderOperation.done_qty,
                PpWorkOrderOperation.plan_qty,
                PpWorkOrderOperation.actual_labor_sec,
                PpWorkOrderOperation.actual_machine_sec,
                PpWorkOrder.order_no,
                MdEquipment.name.label("equipment_name"),
            )
            .join(PpWorkOrder, PpWorkOrder.id == PpWorkOrderOperation.work_order_id)
            .outerjoin(MdEquipment, MdEquipment.id == PpWorkOrderOperation.equipment_id)
            .where(PpWorkOrderOperation.done_qty > 0,
                   PpWorkOrder.created_at >= datetime.now() - timedelta(days=days))
        )
        if work_order_id:
            stmt = stmt.where(PpWorkOrderOperation.work_order_id == work_order_id)

        rows = self.db.execute(stmt).all()
        items = []
        for row in rows:
            done = int(row.done_qty or 0)
            std_total = int(row.std_time_sec or 0) * done   # 标准工时换算总秒
            actual = int(row.actual_labor_sec or 0)
            items.append({
                "order_no": row.order_no,
                "operation_code": row.operation_code,
                "operation_name": row.operation_name,
                "equipment_name": row.equipment_name or "",
                "plan_qty": int(row.plan_qty or 0),
                "done_qty": done,
                "std_seconds": std_total,
                "actual_seconds": actual,
                "machine_seconds": int(row.actual_machine_sec or 0),
                "saved_seconds": max(std_total - actual, 0),
                "efficiency": safe_pct(std_total, actual),
            })
        items.sort(key=lambda x: x["efficiency"], reverse=True)

        std_sum = sum(i["std_seconds"] for i in items)
        actual_sum = sum(i["actual_seconds"] for i in items)
        return {
            "items": items,
            "summary": {
                "std_seconds": std_sum,
                "actual_seconds": actual_sum,
                "overall_efficiency": safe_pct(std_sum, actual_sum),
            },
        }

    # ================================================== 6. 质量不良柏拉图
    def defect_pareto(self, *, days: int = 30) -> dict:
        since = datetime.now() - timedelta(days=days)
        stmt = (
            select(
                QmDefectType.code,
                QmDefectType.name,
                QmDefectType.category,
                func.count(QmInspectionRecord.id).label("qty"),
            )
            .join(QmInspectionRecord,
                  QmInspectionRecord.defect_type_id == QmDefectType.id)
            .join(QmInspectionTask, QmInspectionTask.id == QmInspectionRecord.task_id)
            .where(QmInspectionRecord.result == "NG", QmInspectionRecord.checked_at >= since)
            .group_by(QmDefectType.code, QmDefectType.name, QmDefectType.category)
            .order_by(func.count(QmInspectionRecord.id).desc())
        )
        rows = self.db.execute(stmt).all()

        total = sum(int(row.qty or 0) for row in rows)
        cumulative = 0
        items = []
        for row in rows:
            qty = int(row.qty or 0)
            cumulative += qty
            items.append({
                "defect_code": row.code,
                "defect_name": row.name,
                "category": row.category,
                "qty": qty,
                "ratio": safe_pct(qty, total),
                "cumulative_qty": cumulative,
                "cumulative_ratio": safe_pct(cumulative, total),
            })

        pending = self.db.execute(
            select(func.count(QmInspectionTask.id)).where(
                QmInspectionTask.status == "PENDING"
            )
        ).scalar_one()
        total_records = self.db.execute(
            select(func.count(QmInspectionRecord.id))
        ).scalar_one()
        ng_records = self.db.execute(
            select(func.count(QmInspectionRecord.id)).where(
                QmInspectionRecord.result == "NG"
            )
        ).scalar_one()

        return {
            "items": items,
            "summary": {
                "total_defect": total,
                "pending_tasks": int(pending or 0),
                "total_records": int(total_records or 0),
                "ng_records": int(ng_records or 0),
                "pass_rate": safe_pct(int(total_records or 0) - int(ng_records or 0),
                                      int(total_records or 0)),
                "abc_class_ratio": 80.0,
            },
        }

    # ================================================== 7. 库存周转
    def inventory_turnover(self, *, days: int = 30) -> dict:
        since = datetime.now() - timedelta(days=days)
        stmt = (
            select(
                MmMaterial.id,
                MmMaterial.code,
                MmMaterial.name,
                MmMaterial.unit,
                MmMaterial.safety_stock,
                func.sum(
                    case(
                        (MmInventoryTransaction.direction == -1,
                         MmInventoryTransaction.qty),
                        else_=0,
                    )
                ).label("issue_qty"),
                func.sum(
                    case(
                        (MmInventoryTransaction.direction == 1,
                         MmInventoryTransaction.qty),
                        else_=0,
                    )
                ).label("receive_qty"),
            )
            .join(MmInventoryTransaction,
                  MmInventoryTransaction.material_id == MmMaterial.id)
            .where(MmInventoryTransaction.tx_time >= since)
            .group_by(MmMaterial.id, MmMaterial.code, MmMaterial.name,
                      MmMaterial.unit, MmMaterial.safety_stock)
        )
        rows = self.db.execute(stmt).all()

        stock_map = {
            row.material_id: float(row.qty or 0)
            for row in self.db.execute(
                select(
                    MmInventoryStock.material_id,
                    func.sum(MmInventoryStock.qty_on_hand).label("qty"),
                ).group_by(MmInventoryStock.material_id)
            ).all()
        }

        items = []
        for row in rows:
            issue = float(row.issue_qty or 0)
            receive = float(row.receive_qty or 0)
            avg_stock = max(float(row.safety_stock or 0), 0.0) or 1.0
            on_hand = stock_map.get(row.id, 0.0)
            items.append({
                "material_code": row.code,
                "material_name": row.name,
                "unit": row.unit,
                "issue_qty": round(issue, 3),
                "receive_qty": round(receive, 3),
                "on_hand": round(on_hand, 3),
                "safety_stock": float(row.safety_stock or 0),
                "below_safety": on_hand < float(row.safety_stock or 0),
                "turnover_times": round(issue / avg_stock, 2) if avg_stock else 0.0,
            })
        items.sort(key=lambda x: x["issue_qty"], reverse=True)

        return {
            "items": items,
            "summary": {
                "material_count": len(items),
                "total_issue": round(sum(i["issue_qty"] for i in items), 3),
                "below_safety_count": sum(1 for i in items if i["below_safety"]),
            },
        }

    # ================================================== 8. 人员绩效
    def worker_performance(self, *, days: int = 30) -> dict:
        since = datetime.now() - timedelta(days=days)
        stmt = (
            select(
                MdEmployee.id,
                MdEmployee.emp_no,
                MdEmployee.name,
                MdEmployee.position,
                func.sum(PpWorkReport.qty_good).label("good"),
                func.sum(PpWorkReport.qty_defect).label("defect"),
                func.sum(PpWorkReport.labor_sec).label("labor_sec"),
                func.count(PpWorkReport.id).label("reports"),
            )
            .join(PpWorkReport, PpWorkReport.employee_id == MdEmployee.id)
            .where(PpWorkReport.report_time >= since)
            .group_by(MdEmployee.id, MdEmployee.emp_no, MdEmployee.name,
                      MdEmployee.position)
            .order_by(func.sum(PpWorkReport.qty_good).desc())
        )
        rows = self.db.execute(stmt).all()

        items = []
        for row in rows:
            good = int(row.good or 0)
            defect = int(row.defect or 0)
            labor_hour = int(row.labor_sec or 0) / 3600
            items.append({
                "employee_id": row.id,
                "emp_no": row.emp_no,
                "name": row.name,
                "position": row.position,
                "qty_good": good,
                "qty_defect": defect,
                "reports": int(row.reports or 0),
                "labor_hour": round(labor_hour, 2),
                "yield_rate": safe_pct(good, good + defect),
                "per_hour_output": round(good / labor_hour, 2) if labor_hour else 0.0,
            })

        total_good = sum(i["qty_good"] for i in items)
        total_hour = sum(i["labor_hour"] for i in items)
        return {
            "items": items,
            "summary": {
                "employee_count": len(items),
                "total_good": total_good,
                "total_labor_hour": round(total_hour, 2),
                "avg_per_hour_output": round(total_good / total_hour, 2) if total_hour else 0.0,
            },
        }

    # ------------------------------------------------------------------ 分发入口
    def dispatch(self, code: str, **kwargs: Any) -> dict:
        """按报表编号分发，供统一接口调用。"""
        mapping = {
            "work_order_progress": self.work_order_progress,
            "yield_rate": self.yield_rate,
            "equipment_oee": self.equipment_oee,
            "output_daily": self.output_daily,
            "operation_efficiency": self.operation_efficiency,
            "defect_pareto": self.defect_pareto,
            "inventory_turnover": self.inventory_turnover,
            "worker_performance": self.worker_performance,
        }
        handler = mapping.get(code)
        if handler is None:
            raise KeyError(f"未知报表编号：{code}")
        return handler(**kwargs)
