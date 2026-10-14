"""工单领域服务：状态机 + 事务边界 + 幂等控制 + 库存/质量联动。

这里是**唯一**允许改写工单状态的出口；API 层只做参数校验与权限声明，
任何绕过 :class:`WorkOrderStatus` 合法流转表的写都会被拒绝。

核心流程
--------
1. 创建工单（DRAFT），按工艺路线展开工序、按 BOM 展开物料需求；
2. 下达(RELEASED) → 开工(IN_PROGRESS) → 加工中多次报工 → 完工(COMPLETED)；
3. 报工接口是全系统最重要的写操作，包含四重保护：
   - 幂等键（应用层快照 + 数据库唯一约束）
   - 状态机校验（只有 IN_PROGRESS 可报工）
   - 超量校验（累计报工不得超过计划量）
   - 单事务提交（报工 + 扣料 + SPC 采样子组 + 自动完工，同成功同失败）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    DuplicateReportError,
    NotFoundError,
    StateConflictError,
)
from app.core.idempotency import execute_idempotent
from app.models.inventory import TransactionType
from app.models.inventory import MmMaterial
from app.models.master import (
    MdBom,
    MdBomItem,
    MdProduct,
    MdRouting,
    MdRoutingOperation,
)
from app.models.order import (
    OperationStatus,
    allowed_order_targets,
    PpMaterialRequirement,
    PpWorkOrder,
    PpWorkOrderOperation,
    PpWorkReport,
    WorkOrderStatus,
)
from app.services.inventory_service import InventoryService
from app.services.locking import lock_row
from app.services.spc_service import SPCService
from app.utils import next_no, safe_pct


class OrderService:
    """生产工单服务。"""

    def __init__(self, db: Session):
        self.db = db
        self.inventory = InventoryService(db)
        self.spc = SPCService(db)

    # ==================================================================== 创建
    def create_order(
        self,
        *,
        product_id: int,
        routing_id: int,
        qty_planned: int,
        priority: int = 5,
        workshop_id: int | None = None,
        line_id: int | None = None,
        plan_start: datetime | None = None,
        plan_end: datetime | None = None,
        owner_group: str = "",
        operator: str = "",
        bom_id: int | None = None,
    ) -> PpWorkOrder:
        """新建工单（DRAF），同时展开工序与物料需求。"""
        if qty_planned <= 0:
            raise StateConflictError("计划产量必须大于 0")
        product = self.db.get(MdProduct, product_id)
        if product is None:
            raise NotFoundError("产品不存在")
        routing = self.db.get(MdRouting, routing_id)
        if routing is None:
            raise NotFoundError("工艺路线不存在")

        order = PpWorkOrder(
            order_no=next_no("WO"),
            product_id=product_id,
            routing_id=routing_id,
            bom_id=bom_id,
            workshop_id=workshop_id,
            line_id=line_id,
            qty_planned=qty_planned,
            status=WorkOrderStatus.DRAFT.value,
            priority=priority,
            plan_start=plan_start,
            plan_end=plan_end,
            owner_group=owner_group,
            source="MANUAL",
            remark=f"由 {operator or 'system'} 创建",
        )
        self.db.add(order)
        self.db.flush()

        self._expand_operations(order)
        self._expand_materials(order, product_id, qty_planned, bom_id)
        self.db.flush()
        return order

    def _expand_operations(self, order: PpWorkOrder) -> None:
        """按工艺路线复制工序到工单（业务快照，路由后续变更不影响已建工单）。"""
        stmt = (
            select(MdRoutingOperation)
            .where(MdRoutingOperation.routing_id == order.routing_id)
            .order_by(MdRoutingOperation.seq.asc())
        )
        for src in self.db.execute(stmt).scalars().all():
            op = PpWorkOrderOperation(
                work_order_id=order.id,
                seq=src.seq,
                operation_code=src.operation_code,
                operation_name=src.operation_name,
                routing_operation_id=src.id,
                equipment_id=src.default_equipment_id,
                plan_qty=order.qty_planned,
                std_time_sec=src.std_time_sec,
                status=OperationStatus.NOT_STARTED.value,
                qc_required=src.qc_required,
                spc_enabled=src.spc_enabled,
            )
            self.db.add(op)
        self.db.flush()

    def _expand_materials(self, order: PpWorkOrder, product_id: int,
                          qty_planned: int, bom_id: int | None) -> None:
        """按 BOM 展开物料需求，单位用量已计入损耗率。"""
        if bom_id is None:
            stmt = (
                select(MdBom)
                .where(MdBom.product_id == product_id, MdBom.status == 1)
                .order_by(MdBom.id.desc())
                .limit(1)
            )
            bom = self.db.execute(stmt).scalars().first()
            bom_id = bom.id if bom else None
            if bom:
                order.bom_id = bom.id
        if bom_id is None:
            return

        items = self.db.execute(
            select(MdBomItem).where(MdBomItem.bom_id == bom_id)
        ).scalars().all()

        default_wh = self._default_raw_warehouse()
        for item in items:
            unit_usage = float(item.qty_per_unit) * (1 + float(item.loss_rate))
            req = PpMaterialRequirement(
                work_order_id=order.id,
                material_id=item.material_id,
                warehouse_id=default_wh,
                qty_required=round(unit_usage * qty_planned, 3),
                unit_usage=round(unit_usage, 4),
            )
            self.db.add(req)
        self.db.flush()

    def _default_raw_warehouse(self) -> int:
        from app.models.master import MdWarehouse

        wh = self.db.execute(
            select(MdWarehouse).where(MdWarehouse.category == "RAW").limit(1)
        ).scalars().first()
        if wh is None:
            raise NotFoundError("未初始化原料仓库档案，无法展开物料需求")
        return wh.id

    # ==================================================================== 状态机
    def transition(self, order_id: int, target: str, operator: str = "",
                   reason: str = "") -> PpWorkOrder:
        """统一的工单状态流转入口。"""
        order = self._lock_order(order_id)
        current = WorkOrderStatus(order.status)
        if not current.can_transition_to(target):
            raise StateConflictError(
                f"工单 {order.order_no} 当前状态 {current.value} 不能流转到 {target}"
            )

        target_status = WorkOrderStatus(target)

        if target_status == WorkOrderStatus.RELEASED:
            self._guard_has_operations(order)
            order.released_by = operator

        elif target_status == WorkOrderStatus.IN_PROGRESS:
            order.actual_start = order.actual_start or datetime.now()
            self._start_first_operation(order)

        elif target_status == WorkOrderStatus.COMPLETED:
            self._guard_all_operations_finished(order)
            order.actual_end = datetime.now()
            self._receiving_finished_goods(order, operator)

        elif target_status == WorkOrderStatus.CANCELLED:
            order.remark = f"作废原因：{reason or '未填写'}"

        order.status = target_status.value
        order.version = int(order.version or 0) + 1
        self.db.flush()
        return order

    def allowed_transitions(self, order_id: int) -> list[str]:
        """返回当前状态允许的下一步操作，前端据此渲染按钮。"""
        order = self._get_order(order_id)
        return allowed_order_targets(order.status)

    # ------------------------------ 状态机内部守卫 ------------------------------
    def _guard_has_operations(self, order: PpWorkOrder) -> None:
        count = self.db.query(PpWorkOrderOperation).filter(
            PpWorkOrderOperation.work_order_id == order.id
        ).count()
        if count == 0:
            raise StateConflictError("工单未展开工序，不能下达")

    def _guard_all_operations_finished(self, order: PpWorkOrder) -> None:
        pending = self.db.query(PpWorkOrderOperation).filter(
            PpWorkOrderOperation.work_order_id == order.id,
            PpWorkOrderOperation.status != OperationStatus.FINISHED.value,
        ).count()
        if pending:
            raise StateConflictError(
                f"仍有 {pending} 道工序未完成，不能完工；请先完成全部工序报工"
            )

    def _start_first_operation(self, order: PpWorkOrder) -> None:
        first = self.db.query(PpWorkOrderOperation).filter(
            PpWorkOrderOperation.work_order_id == order.id,
            PpWorkOrderOperation.status == OperationStatus.NOT_STARTED.value,
        ).order_by(PpWorkOrderOperation.seq.asc()).first()
        if first:
            first.status = OperationStatus.RUNNING.value
            first.started_at = datetime.now()

    def _receiving_finished_goods(self, order: PpWorkOrder, operator: str) -> None:
        """完工自动入库：合格品数量写入成品仓。"""
        from app.models.master import MdWarehouse

        fg = self.db.execute(
            select(MdWarehouse).where(MdWarehouse.category == "FG").limit(1)
        ).scalars().first()
        if fg is None:
            return
        qty = int(order.qty_good or 0)
        if qty <= 0:
            return
        self.inventory.receive(
            material_id=self._finished_material_id(order.product_id),
            warehouse_id=fg.id,
            qty=float(qty),
            tx_type=TransactionType.FINISH_IN.value,
            ref_type="WORK_ORDER",
            ref_id=order.order_no,
            work_order_id=order.id,
            operator_no=operator,
        )

    def _finished_material_id(self, product_id: int) -> int:
        """成品同时也是物料：按 code 复用同一条物料档案。"""
        from app.models.inventory import MmMaterial

        product = self.db.get(MdProduct, product_id)
        material = self.db.execute(
            select(MmMaterial).where(MmMaterial.code == product.code)
        ).scalars().first()
        if material is None:
            material = MmMaterial(
                code=product.code, name=product.name, spec=product.spec,
                unit=product.unit, category="FG", unit_price=0.0,
            )
            self.db.add(material)
            self.db.flush()
        return material.id

    # ==================================================================== 报工
    def report_work(
        self,
        *,
        work_order_id: int,
        operation_id: int,
        qty_good: int,
        qty_defect: int = 0,
        employee_id: int | None = None,
        shift_id: int | None = None,
        labor_sec: int = 0,
        machine_sec: int = 0,
        measurements: list[float] | None = None,
        idempotency_key: str | None = None,
        operator: str = "",
    ) -> tuple[dict, bool]:
        """工序报工（幂等 + 事务 + 库存联动 + SPC 采样）。

        :return: ``(结果, 是否命中重复请求)``
        """
        payload = {
            "work_order_id": work_order_id,
            "operation_id": operation_id,
            "qty_good": qty_good,
            "qty_defect": qty_defect,
            "employee_id": employee_id,
            "shift_id": shift_id,
            "labor_sec": labor_sec,
            "machine_sec": machine_sec,
            "measurements": measurements or [],
        }
        key = idempotency_key or f"AUTO:{operator}:{work_order_id}:{operation_id}:{next_no('IK')}"
        return execute_idempotent(
            self.db,
            key=key,
            scope="work_report",
            payload=payload,
            operator=operator,
            handler=lambda: self._do_report(**payload, operator=operator,
                                            idempotency_key=key),
        )

    def _do_report(self, *, work_order_id: int, operation_id: int, qty_good: int,
                   qty_defect: int, employee_id: int | None, shift_id: int | None,
                   labor_sec: int, machine_sec: int, measurements: list[float],
                   operator: str, idempotency_key: str) -> dict:
        """真正的报工执行体，被幂等包裹。"""
        if qty_good < 0 or qty_defect < 0:
            raise StateConflictError("报工数量不能为负")
        if qty_good + qty_defect <= 0:
            raise StateConflictError("报工数量必须大于 0")

        order = self._lock_order(work_order_id)
        if order.status != WorkOrderStatus.IN_PROGRESS.value:
            raise StateConflictError(
                f"工单 {order.order_no} 状态为 {order.status}，仅可报工处于 IN_PROGRESS 的工单"
            )

        operation = self.db.get(PpWorkOrderOperation, operation_id)
        if operation is None or operation.work_order_id != work_order_id:
            raise NotFoundError("工序不存在或不属于该工单")
        if operation.status == OperationStatus.FINISHED.value:
            raise DuplicateReportError("该工序已完成，不能再报工")

        total = qty_good + qty_defect
        remain = int(operation.plan_qty) - int(operation.done_qty)
        if total > remain:
            raise StateConflictError(
                f"本次报工 {total} 件超过工序剩余计划量 {remain} 件"
            )

        # ---- 1. 写报工记录（唯一约束兜底幂等）----
        report = PpWorkReport(
            report_no=next_no("RP"),
            work_order_id=work_order_id,
            operation_id=operation_id,
            employee_id=employee_id,
            equipment_id=operation.equipment_id,
            shift_id=shift_id,
            qty_good=qty_good,
            qty_defect=qty_defect,
            labor_sec=labor_sec or int(total * int(operation.std_time_sec or 0)),
            machine_sec=machine_sec,
            report_time=datetime.now(),
            # 与幂等记录同源：即使应用层被绕过，这里的数据层唯一约束也会拦住重复报工
            idempotency_key=idempotency_key,
        )
        self.db.add(report)

        # ---- 2. 累计工序数量 ----
        operation.done_qty = int(operation.done_qty) + total
        operation.good_qty = int(operation.good_qty) + qty_good
        operation.defect_qty = int(operation.defect_qty) + qty_defect
        operation.actual_labor_sec = int(operation.actual_labor_sec) + int(report.labor_sec)
        operation.actual_machine_sec = int(operation.actual_machine_sec) + machine_sec
        operation.status = OperationStatus.RUNNING.value
        operation.started_at = operation.started_at or datetime.now()

        # ---- 3. 末道工序的产出即为工单产出 ----
        auto_completed = False
        if self._is_last_operation(operation):
            order.qty_completed = operation.done_qty
            order.qty_good = operation.good_qty
            order.qty_defect = operation.defect_qty

        if operation.done_qty >= operation.plan_qty:
            operation.status = OperationStatus.FINISHED.value
            operation.finished_at = datetime.now()
            self._activate_next_operation(order, operation)

        self.db.flush()

        # ---- 4. 库存联动：按合格数扣料 ----
        flows = self.inventory.consume_for_report(
            work_order_id=work_order_id,
            good_qty=qty_good,
            operator_no=operator,
            ref_id=operation.operation_code,
        )
        report.inventory_flows = json.dumps(flows, ensure_ascii=False)

        # ---- 5. SPC 采样 + 判异联动 ----
        spc_result: dict | None = None
        if operation.spc_enabled and measurements:
            spc_result = self.spc.record_subgroup(
                product_id=order.product_id,
                operation_code=operation.operation_code,
                values=measurements,
                work_order_id=order.id,
                operation_id=operation.id,
                **self._spc_spec_defaults(operation),
            )

        # ---- 6. 全部工序完成 → 自动完工 ----
        if self._all_finished(order):
            if WorkOrderStatus(order.status).can_transition_to(
                WorkOrderStatus.COMPLETED.value
            ):
                self.transition(order.id, WorkOrderStatus.COMPLETED.value, operator)
                auto_completed = True

        return {
            "report_no": report.report_no,
            "order_no": order.order_no,
            "operation_name": operation.operation_name,
            "qty_good": qty_good,
            "qty_defect": qty_defect,
            "operation_done_qty": int(operation.done_qty),
            "operation_status": operation.status,
            "order_progress": order.progress,
            "order_yield_rate": order.yield_rate,
            "inventory_flows": flows,
            "auto_completed": auto_completed,
            "spc": spc_result,
        }

    def _spc_spec_defaults(self, operation: PpWorkOrderOperation) -> dict:
        """从工艺工序取 SPC 的 CTQ 参数。"""
        src = (
            self.db.get(MdRoutingOperation, operation.routing_operation_id)
            if operation.routing_operation_id else None
        )
        if src is None:
            return {"feature_name": operation.operation_name}
        return {
            "feature_name": src.spc_feature_name or operation.operation_name,
            "nominal": float(src.spc_nominal or 0),
            "upper_spec": float(src.spc_upper or 0),
            "lower_spec": float(src.spc_lower or 0),
        }

    def _is_last_operation(self, operation: PpWorkOrderOperation) -> bool:
        last = self.db.query(PpWorkOrderOperation).filter(
            PpWorkOrderOperation.work_order_id == operation.work_order_id
        ).order_by(PpWorkOrderOperation.seq.desc()).first()
        return last is not None and last.id == operation.id

    def _activate_next_operation(self, order: PpWorkOrder,
                                 finished: PpWorkOrderOperation) -> None:
        nxt = self.db.query(PpWorkOrderOperation).filter(
            PpWorkOrderOperation.work_order_id == order.id,
            PpWorkOrderOperation.seq > finished.seq,
            PpWorkOrderOperation.status == OperationStatus.NOT_STARTED.value,
        ).order_by(PpWorkOrderOperation.seq.asc()).first()
        if nxt:
            nxt.status = OperationStatus.RUNNING.value
            nxt.started_at = datetime.now()

    def _all_finished(self, order: PpWorkOrder) -> bool:
        pending = self.db.query(PpWorkOrderOperation).filter(
            PpWorkOrderOperation.work_order_id == order.id,
            PpWorkOrderOperation.status != OperationStatus.FINISHED.value,
        ).count()
        return pending == 0

    # ==================================================================== 查询
    def _get_order(self, order_id: int) -> PpWorkOrder:
        order = self.db.get(PpWorkOrder, order_id)
        if order is None:
            raise NotFoundError("工单不存在")
        return order

    def _lock_order(self, order_id: int) -> PpWorkOrder:
        order = lock_row(
            self.db, select(PpWorkOrder).where(PpWorkOrder.id == order_id)
        )
        if order is None:
            raise NotFoundError("工单不存在")
        return order

    def get_order(self, order_id: int) -> PpWorkOrder:
        return self._get_order(order_id)

    def detail(self, order_id: int) -> dict:
        """工单详情：主信息 + 工序清单 + 物料需求 + 报工流水。"""
        order = self._get_order(order_id)
        operations = list(
            self.db.execute(
                select(PpWorkOrderOperation)
                .where(PpWorkOrderOperation.work_order_id == order_id)
                .order_by(PpWorkOrderOperation.seq.asc())
            ).scalars().all()
        )
        materials = list(
            self.db.execute(
                select(PpMaterialRequirement)
                .where(PpMaterialRequirement.work_order_id == order_id)
            ).scalars().all()
        )
        material_names = {
            row.id: (row.code, row.name, row.unit)
            for row in self.db.execute(select(MmMaterial)).scalars().all()
        }
        reports = list(
            self.db.execute(
                select(PpWorkReport)
                .where(PpWorkReport.work_order_id == order_id)
                .order_by(PpWorkReport.id.desc())
                .limit(20)
            ).scalars().all()
        )
        return {
            "order": order,
            "operations": operations,
            "materials": materials,
            "material_names": material_names,
            "reports": reports,
            "allowed_transitions": allowed_order_targets(order.status),
            "summary": {
                "progress": order.progress,
                "yield_rate": order.yield_rate,
                "defect_rate": safe_pct(order.qty_defect, order.qty_completed),
            },
        }

    def list_orders(self, *, status: str | None = None, product_id: int | None = None,
                    keyword: str | None = None, limit: int = 100) -> list[PpWorkOrder]:
        stmt = select(PpWorkOrder)
        if status:
            stmt = stmt.where(PpWorkOrder.status == status)
        if product_id:
            stmt = stmt.where(PpWorkOrder.product_id == product_id)
        if keyword:
            stmt = stmt.where(PpWorkOrder.order_no.like(f"%{keyword}%"))
        stmt = stmt.order_by(PpWorkOrder.id.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().unique().all())

    # ==================================================================== 统计
    def progress_matrix(self) -> dict[str, Any]:
        """各状态工单数与总计划/完成量，用于看板卡片。"""
        rows = self.db.execute(
            select(PpWorkOrder.status, PpWorkOrder.qty_planned, PpWorkOrder.qty_completed)
        ).all()
        by_status: dict[str, int] = {}
        planned = completed = 0
        for status, plan, done in rows:
            by_status[status] = by_status.get(status, 0) + 1
            planned += int(plan or 0)
            completed += int(done or 0)
        return {
            "total": sum(by_status.values()),
            "by_status": by_status,
            "qty_planned": planned,
            "qty_completed": completed,
            "completion_rate": safe_pct(completed, planned),
        }
