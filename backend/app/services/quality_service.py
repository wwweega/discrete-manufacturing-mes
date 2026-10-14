"""质量检验服务。

两类质检单来源：

* **SPC 自动告警**：控制图判异后由 :class:`SPCService` 调用
  :meth:`QualityService.create_from_spc_alert` 生成，状态为 ``PENDING``；
* **人工报检 / 抽检**：调用 :meth:`QualityService.create_manual`。

质检结论回填后联动更新工单合格数/不良数，形成质量闭环。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, StateConflictError
from app.models.order import PpWorkOrder, PpWorkOrderOperation
from app.models.quality import (
    InspectionSource,
    InspectionStatus,
    QmInspectionRecord,
    QmInspectionTask,
    QmSpcSubgroup,
)
from app.services.spc_core import RULE_DESCRIPTIONS
from app.utils import next_no

#: 允许流转的质检单状态
_ALLOWED_NEXT = {
    InspectionStatus.PENDING.value: {InspectionStatus.TESTING.value,
                                     InspectionStatus.CLOSED.value},
    InspectionStatus.TESTING.value: {InspectionStatus.PASSED.value,
                                     InspectionStatus.FAILED.value},
    InspectionStatus.PASSED.value: {InspectionStatus.CLOSED.value},
    InspectionStatus.FAILED.value: {InspectionStatus.CLOSED.value},
    InspectionStatus.CLOSED.value: set(),
}


class QualityService:
    """质检单生命周期管理。"""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ 创建
    def create_from_spc_alert(
        self,
        *,
        subgroup: QmSpcSubgroup,
        rules: list[str],
        mean_value: float,
        product_id: int | None = None,
        work_order_id: int | None = None,
        operation_id: int | None = None,
    ) -> QmInspectionTask:
        """SPC 判异 → 自动生成待处理质检单（同一子组只生成一次）。"""
        exist = (
            self.db.query(QmInspectionTask)
            .filter(QmInspectionTask.spc_subgroup_id == subgroup.id)
            .first()
        )
        if exist is not None:
            return exist

        rule_text = "、".join(RULE_DESCRIPTIONS.get(r, r) for r in rules)
        task = QmInspectionTask(
            task_no=next_no("QC"),
            work_order_id=work_order_id or subgroup.work_order_id,
            operation_id=operation_id or subgroup.operation_id,
            product_id=product_id or subgroup.product_id,
            source=InspectionSource.SPC_ALERT.value,
            status=InspectionStatus.PENDING.value,
            sample_qty=subgroup.subgroup_size,
            trigger_reason=(
                f"SPC X̄-R 控制图异常：第 {subgroup.subgroup_no} 号子组均值 {mean_value:.4f}"
                f"，命中判异准则 {rule_text}"
            ),
            inspector_no="",
            assigned_at=datetime.now(),
        )
        self.db.add(task)
        self.db.flush()
        return task

    def create_manual(
        self,
        *,
        product_id: int,
        work_order_id: int | None = None,
        operation_id: int | None = None,
        sample_qty: int = 5,
        inspector_no: str = "",
        reason: str = "人工报检",
    ) -> QmInspectionTask:
        """人工发起质检单。"""
        task = QmInspectionTask(
            task_no=next_no("QC"),
            work_order_id=work_order_id,
            operation_id=operation_id,
            product_id=product_id,
            source=InspectionSource.MANUAL.value,
            status=InspectionStatus.PENDING.value,
            sample_qty=sample_qty,
            trigger_reason=reason,
            inspector_no=inspector_no,
            assigned_at=datetime.now(),
        )
        self.db.add(task)
        self.db.flush()
        return task

    # ------------------------------------------------------------------ 流转
    def transition(self, task_id: int, target: str, operator: str = "") -> QmInspectionTask:
        """质检单状态流转，并检查目标是否合法。"""
        task = self.db.get(QmInspectionTask, task_id)
        if task is None:
            raise NotFoundError("质检单不存在")
        if target not in _ALLOWED_NEXT.get(task.status, set()):
            raise StateConflictError(f"质检单当前状态 {task.status} 不能流转到 {target}")
        task.status = target
        task.inspector_no = operator or task.inspector_no
        if target in (InspectionStatus.PASSED.value, InspectionStatus.FAILED.value):
            task.conclusion = "合格" if target == InspectionStatus.PASSED.value else "不合格"
        if target == InspectionStatus.CLOSED.value:
            task.closed_at = datetime.now()
        self.db.flush()
        return task

    # ------------------------------------------------------------------ 记录
    def add_record(
        self,
        *,
        task_id: int,
        seq: int,
        measured_value: float,
        nominal: float = 0.0,
        tolerance_upper: float = 0.0,
        tolerance_lower: float = 0.0,
        defect_type_id: int | None = None,
        feature_name: str = "",
    ) -> QmInspectionRecord:
        """录入单件检验记录，并按公差自动判定 OK / NG。"""
        task = self.db.get(QmInspectionTask, task_id)
        if task is None:
            raise NotFoundError("质检单不存在")

        if tolerance_upper > tolerance_lower:
            result = "OK" if tolerance_lower <= measured_value <= tolerance_upper else "NG"
        else:
            result = "OK"

        record = QmInspectionRecord(
            task_id=task_id,
            seq=seq,
            feature_name=feature_name,
            measured_value=measured_value,
            nominal=nominal,
            tolerance_upper=tolerance_upper,
            tolerance_lower=tolerance_lower,
            result=result,
            defect_type_id=None if result == "OK" else defect_type_id,
            checked_at=datetime.now(),
        )
        self.db.add(record)
        self.db.flush()

        # 回写抽检数量与不良数
        total = self.db.query(QmInspectionRecord).filter(
            QmInspectionRecord.task_id == task_id
        ).count()
        ng = self.db.query(QmInspectionRecord).filter(
            QmInspectionRecord.task_id == task_id,
            QmInspectionRecord.result == "NG",
        ).count()
        task.sample_qty = total
        task.defect_qty = ng
        self.db.flush()
        return record

    # ------------------------------------------------------------------ 查询
    def pending_count(self) -> int:
        """待处理质检单数量（看板告警区使用）。"""
        stmt = select(QmInspectionTask).where(
            QmInspectionTask.status == InspectionStatus.PENDING.value
        )
        return len(self.db.execute(stmt).scalars().all())

    def list_tasks(
        self, *, status: str | None = None, source: str | None = None,
        work_order_id: int | None = None, limit: int = 100,
    ) -> list[QmInspectionTask]:
        stmt = select(QmInspectionTask)
        if status:
            stmt = stmt.where(QmInspectionTask.status == status)
        if source:
            stmt = stmt.where(QmInspectionTask.source == source)
        if work_order_id:
            stmt = stmt.where(QmInspectionTask.work_order_id == work_order_id)
        stmt = stmt.order_by(QmInspectionTask.id.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def summarize_task(self, task: QmInspectionTask) -> dict:
        """把工单 / 工序信息拼成前端可直接展示的摘要。"""
        order = self.db.get(PpWorkOrder, task.work_order_id) if task.work_order_id else None
        operation = (
            self.db.get(PpWorkOrderOperation, task.operation_id) if task.operation_id else None
        )
        return {
            "id": task.id,
            "task_no": task.task_no,
            "order_no": order.order_no if order else "",
            "operation_name": operation.operation_name if operation else "",
            "source": task.source,
            "status": task.status,
            "sample_qty": task.sample_qty,
            "defect_qty": task.defect_qty,
            "trigger_reason": task.trigger_reason,
            "conclusion": task.conclusion,
            "inspector_no": task.inspector_no,
            "assigned_at": task.assigned_at,
            "closed_at": task.closed_at,
        }
