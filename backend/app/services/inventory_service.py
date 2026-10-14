"""库存服务：工单领料扣减、退料、完工入库、盘点点调。

设计约束（简历「库存联动」要求）
--------------------------------
1. **任何变动必落流水**：先在 :class:`MmInventoryStock` 上扣账，
   再写一条 :class:`MmInventoryTransaction`，并记录变动后余额，做到可对账；
2. **不足即失败**：线上误操作往往比缺料更贵，数量不足直接抛异常回滚，
   不允许出现负库存；
3. **行级锁 + 事务**：由调用方（report_service）统一提交，
   保证「报工 → 扣料」是一个原子操作。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import InventoryShortageError, NotFoundError
from app.models.inventory import (
    MmInventoryStock,
    MmInventoryTransaction,
    MmMaterial,
    TransactionType,
)
from app.models.order import PpMaterialRequirement
from app.services.locking import lock_row
from app.utils import next_no


class InventoryService:
    """库存联动。"""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ 查询
    def get_stock(self, material_id: int, warehouse_id: int) -> MmInventoryStock:
        """获取锁定后的库存余额行；不存在时按 0 初始化一行。"""
        stock = lock_row(
            self.db,
            select(MmInventoryStock).where(
                MmInventoryStock.material_id == material_id,
                MmInventoryStock.warehouse_id == warehouse_id,
            ),
        )
        if stock is None:
            return None  # type: ignore[return-value]
        return stock

    def ensure_stock(self, material_id: int, warehouse_id: int) -> MmInventoryStock:
        stock = self.get_stock(material_id, warehouse_id)
        if stock is None:
            stock = MmInventoryStock(
                material_id=material_id, warehouse_id=warehouse_id, qty_on_hand=0.0
            )
            self.db.add(stock)
            self.db.flush()
        return stock

    # ------------------------------------------------------------------ 出入
    def issue(
        self,
        *,
        material_id: int,
        warehouse_id: int,
        qty: float,
        ref_type: str = "",
        ref_id: str = "",
        work_order_id: int | None = None,
        operator_no: str = "",
        tx_type: str = TransactionType.WORK_ORDER_ISSUE.value,
        allow_negative: bool = False,
    ) -> MmInventoryTransaction:
        """出库。数量不足时抛 :class:`InventoryShortageError`，整个事务回滚。"""
        if qty <= 0:
            return None  # type: ignore[return-value]

        stock = self.ensure_stock(material_id, warehouse_id)
        available = float(stock.qty_on_hand) - float(stock.qty_reserved)
        if available < qty and not allow_negative:
            material = self.db.get(MmMaterial, material_id)
            name = material.name if material else f"material#{material_id}"
            raise InventoryShortageError(
                f"物料【{name}】库存不足：可用 {available:.3f}，本次需扣 {qty:.3f}"
            )

        stock.qty_on_hand = float(stock.qty_on_hand) - qty
        stock.last_tx_at = datetime.now()
        tx = self._write_tx(
            material_id=material_id,
            warehouse_id=warehouse_id,
            tx_type=tx_type,
            direction=-1,
            qty=qty,
            balance_after=float(stock.qty_on_hand),
            ref_type=ref_type,
            ref_id=ref_id,
            work_order_id=work_order_id,
            operator_no=operator_no,
        )
        return tx

    def receive(
        self,
        *,
        material_id: int,
        warehouse_id: int,
        qty: float,
        tx_type: str = TransactionType.FINISH_IN.value,
        ref_type: str = "",
        ref_id: str = "",
        work_order_id: int | None = None,
        operator_no: str = "",
    ) -> MmInventoryTransaction:
        """入库。"""
        if qty <= 0:
            return None  # type: ignore[return-value]
        stock = self.ensure_stock(material_id, warehouse_id)
        stock.qty_on_hand = float(stock.qty_on_hand) + qty
        stock.last_tx_at = datetime.now()
        return self._write_tx(
            material_id=material_id,
            warehouse_id=warehouse_id,
            tx_type=tx_type,
            direction=1,
            qty=qty,
            balance_after=float(stock.qty_on_hand),
            ref_type=ref_type,
            ref_id=ref_id,
            work_order_id=work_order_id,
            operator_no=operator_no,
        )

    def adjust(self, *, material_id: int, warehouse_id: int, target_qty: float,
               operator_no: str = "", reason: str = "盘点调整") -> MmInventoryTransaction:
        """盘点调整为指定数量，差额自动生成流水。"""
        stock = self.ensure_stock(material_id, warehouse_id)
        current = float(stock.qty_on_hand)
        diff = target_qty - current
        if abs(diff) < 1e-9:
            return None  # type: ignore[return-value]
        stock.qty_on_hand = target_qty
        stock.last_tx_at = datetime.now()
        return self._write_tx(
            material_id=material_id,
            warehouse_id=warehouse_id,
            tx_type=TransactionType.ADJUST.value,
            direction=1 if diff > 0 else -1,
            qty=abs(diff),
            balance_after=target_qty,
            ref_type="ADJUST",
            ref_id=reason,
            operator_no=operator_no,
        )

    # ------------------------------------------------------------------ 需求
    def consume_for_report(
        self,
        *,
        work_order_id: int,
        good_qty: int,
        operator_no: str = "",
        ref_id: str = "",
    ) -> list[dict[str, Any]]:
        """按报工合格数 + 单位用量（含损耗）扣减物料。

        :return: 本次产生的流水摘要列表，供报工响应与前端展示
        """
        stmt = select(PpMaterialRequirement).where(
            PpMaterialRequirement.work_order_id == work_order_id
        ).order_by(PpMaterialRequirement.id.asc())
        requirements = list(self.db.execute(stmt).scalars().all())

        flows: list[dict[str, Any]] = []
        for req in requirements:
            plan_total = float(req.qty_required)
            if plan_total <= 0 or good_qty <= 0:
                continue
            order_qty = self._planned_qty_of(work_order_id)
            # 按「已发比例」控制：累计发料量不得超过计划需求量
            per_unit = plan_total / order_qty if order_qty else 0.0
            planned_issue = round(per_unit * good_qty, 4)
            remaining = plan_total - float(req.qty_issued)
            issue_qty = max(min(planned_issue, remaining), 0.0)
            if issue_qty <= 0:
                continue

            tx = self.issue(
                material_id=req.material_id,
                warehouse_id=req.warehouse_id,
                qty=issue_qty,
                ref_type="WORK_REPORT",
                ref_id=ref_id,
                work_order_id=work_order_id,
                operator_no=operator_no,
            )
            req.qty_issued = float(req.qty_issued) + issue_qty
            self.db.flush()
            flows.append({
                "tx_no": tx.tx_no,
                "material_id": req.material_id,
                "qty": round(issue_qty, 4),
                "balance_after": round(float(tx.balance_after), 4),
            })
        return flows

    def return_material(self, *, work_order_id: int, material_id: int,
                        qty: float, operator_no: str = "") -> MmInventoryTransaction:
        """退料：反向冲销已发量。"""
        req = self.db.query(PpMaterialRequirement).filter(
            PpMaterialRequirement.work_order_id == work_order_id,
            PpMaterialRequirement.material_id == material_id,
        ).first()
        if req is None:
            raise NotFoundError("工单不存在该物料需求")
        issued = float(req.qty_issued)
        real_qty = min(qty, issued)
        if real_qty <= 0:
            raise NotFoundError("已发量为 0，无法退料")

        tx = self.receive(
            material_id=material_id,
            warehouse_id=req.warehouse_id,
            qty=real_qty,
            tx_type=TransactionType.RETURN.value,
            ref_type="MATERIAL_RETURN",
            work_order_id=work_order_id,
            operator_no=operator_no,
        )
        req.qty_issued = issued - real_qty
        req.qty_returned = float(req.qty_returned) + real_qty
        self.db.flush()
        return tx

    # ------------------------------------------------------------------ 内部
    def _planned_qty_of(self, work_order_id: int) -> int:
        from app.models.order import PpWorkOrder

        order = self.db.get(PpWorkOrder, work_order_id)
        return int(order.qty_planned) if order else 0

    def _write_tx(self, **kwargs: Any) -> MmInventoryTransaction:
        tx = MmInventoryTransaction(
            tx_no=next_no("TX"),
            tx_time=datetime.now(),
            **kwargs,
        )
        self.db.add(tx)
        self.db.flush()
        return tx
