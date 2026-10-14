"""示例数据播种脚本。

用法::

    python -m scripts.seed              # 幂等播种（已存在数据则跳过）
    python -m scripts.seed --reset      # 删库重建后全量播种
    python -m scripts.seed --gateway 30 # 额外让数采网关采集 30 帧

生成内容分为两部分：

1. **主数据**：车间 / 产线 / 设备 / 员工 / 班次 / 产品 / BOM / 工艺路线 / 物料 / 仓库，
   属于静态档案，任何环境都一样；
2. **演示业务数据**：近 30 天的工单、报工记录、SPC 子组、库存流水，
   由固定随机种子生成，**可复现**，用于让报表与看板有真实数据可展示。

所有演示数据在数据库中均带有可识别的单号前缀（``WO/RP/QC/TX``），
与真实业务数据无本质区别，便于直接演示完整链路。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.models import count_tables  # noqa: E402
from app.models.inventory import MmInventoryStock, MmMaterial  # noqa: E402
from app.models.master import (  # noqa: E402
    MdBom,
    MdBomItem,
    MdEmployee,
    MdEquipment,
    MdProduct,
    MdProductionLine,
    MdRouting,
    MdRoutingOperation,
    MdShift,
    MdSupplier,
    MdWarehouse,
    MdWorkshop,
)
from app.models.order import (  # noqa: E402
    OperationStatus,
    PpWorkOrder,
    PpWorkOrderOperation,
    PpWorkReport,
    WorkOrderStatus,
)
from app.models.quality import InspectionStatus, QmDefectType  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.order_service import OrderService  # noqa: E402
from app.services.quality_service import QualityService  # noqa: E402

RNG = random.Random(20260301)

PRODUCTS = [
    {"code": "GF-200", "name": "精密齿轮箱总成", "spec": "GF-200-A", "unit": "PCS",
     "std_cycle_sec": 420, "bom_code": "BOM-GF200", "cycle": 4},
    {"code": "MD-120", "name": "主轴电机座", "spec": "MD-120-B", "unit": "PCS",
     "std_cycle_sec": 300, "bom_code": "BOM-MD120", "cycle": 3},
    {"code": "FL-80", "name": "法兰盘组件", "spec": "FL-80-C", "unit": "PCS",
     "std_cycle_sec": 180, "bom_code": "BOM-FL80", "cycle": 3},
]

MATERIALS = [
    {"code": "RM-STEEL45", "name": "45#圆钢", "spec": "Φ60", "unit": "KG",
     "category": "RAW", "unit_price": 6.2, "safety_stock": 2000, "init_qty": 18000},
    {"code": "RM-ALU6061", "name": "铝合金棒6061", "spec": "Φ40", "unit": "KG",
     "category": "RAW", "unit_price": 18.5, "safety_stock": 800, "init_qty": 6500},
    {"code": "RM-CAST250", "name": "铸铁毛坯HT250", "spec": "定制", "unit": "PCS",
     "category": "RAW", "unit_price": 42.0, "safety_stock": 300, "init_qty": 2600},
    {"code": "RM-BEARING", "name": "深沟球轴承6205", "spec": "6205-2RS", "unit": "PCS",
     "category": "RAW", "unit_price": 23.8, "safety_stock": 500, "init_qty": 4200},
    {"code": "RM-BOLT", "name": "高强度螺栓M10", "spec": "M10×40", "unit": "PCS",
     "category": "RAW", "unit_price": 1.4, "safety_stock": 3000, "init_qty": 26000},
    {"code": "RM-OILSEAL", "name": "骨架油封", "spec": "35×55×10", "unit": "PCS",
     "category": "RAW", "unit_price": 4.6, "safety_stock": 600, "init_qty": 3800},
]

OPERATION_TEMPLATE = [
    {"code": "OP10", "name": "下料", "std_time_sec": 60, "setup_time_sec": 300,
     "qc_required": False, "spc_enabled": False},
    {"code": "OP20", "name": "车削加工", "std_time_sec": 180, "setup_time_sec": 420,
     "qc_required": False, "spc_enabled": True,
     "feature": "内孔直径", "nominal": 40.0, "upper": 40.05, "lower": 39.95},
    {"code": "OP30", "name": "铣削加工", "std_time_sec": 150, "setup_time_sec": 360,
     "qc_required": False, "spc_enabled": True,
     "feature": "端面跳动", "nominal": 25.0, "upper": 25.04, "lower": 24.96},
    {"code": "OP40", "name": "终检喷码", "std_time_sec": 40, "setup_time_sec": 120,
     "qc_required": True, "spc_enabled": False},
]

BOM_MAPPING = {
    "GF-200": [("RM-CAST250", 1.0, 0.02), ("RM-BEARING", 2.0, 0.01),
               ("RM-BOLT", 8.0, 0.03), ("RM-OILSEAL", 1.0, 0.02)],
    "MD-120": [("RM-ALU6061", 2.4, 0.04), ("RM-BOLT", 6.0, 0.03),
               ("RM-OILSEAL", 2.0, 0.02)],
    "FL-80": [("RM-STEEL45", 1.6, 0.03), ("RM-BOLT", 4.0, 0.03)],
}

EMPLOYEES = [
    {"emp_no": "EMP001", "name": "张建国", "position": "LEADER"},
    {"emp_no": "EMP002", "name": "王志强", "position": "OPERATOR"},
    {"emp_no": "EMP003", "name": "李晓梅", "position": "OPERATOR"},
    {"emp_no": "EMP004", "name": "陈立新", "position": "INSPECTOR"},
    {"emp_no": "EMP005", "name": "刘海涛", "position": "OPERATOR"},
]

DEFECT_TYPES = [
    {"code": "D01", "name": "尺寸超差", "category": "尺寸", "severity": "MAJOR"},
    {"code": "D02", "name": "表面划伤", "category": "外观", "severity": "MINOR"},
    {"code": "D03", "name": "磕碰变形", "category": "外观", "severity": "MAJOR"},
    {"code": "D04", "name": "孔位偏移", "category": "尺寸", "severity": "CRITICAL"},
    {"code": "D05", "name": "装配卡死", "category": "性能", "severity": "CRITICAL"},
]

EQUIPMENT = [
    {"code": "EQ-L1-01", "name": "数控车床CK6140", "model": "CK6140", "line": "LINE-A",
     "rated_speed": 1800, "rated_output": 60},
    {"code": "EQ-L1-02", "name": "立式加工中心VMC850", "model": "VMC850", "line": "LINE-A",
     "rated_speed": 8000, "rated_output": 45},
    {"code": "EQ-L2-01", "name": "数控车床CK6150", "model": "CK6150", "line": "LINE-B",
     "rated_speed": 1600, "rated_output": 55},
    {"code": "EQ-L2-02", "name": "卧式铣床X6132", "model": "X6132", "line": "LINE-B",
     "rated_speed": 1500, "rated_output": 40},
    {"code": "EQ-L2-03", "name": "三坐标测量机", "model": "ZC-1200", "line": "LINE-B",
     "rated_speed": 0, "rated_output": 30},
]


# ===========================================================================
# 主数据
# ===========================================================================
def seed_master_data(db) -> dict:
    """写入静态档案数据（幂等）。"""
    stats = {}
    if db.execute(select(func.count(MdWorkshop.id))).scalar_one() > 0:
        return {"skipped": True}

    supplier = MdSupplier(code="SUP-001", name="厦门恒锐精密机械有限公司",
                          contact="章经理", phone="0592-8899001", qualification="A")
    supplier2 = MdSupplier(code="SUP-002", name="泉州华冶金属材料有限公司",
                           contact="林主管", phone="0595-8877002", qualification="A")
    db.add_all([supplier, supplier2])

    workshop = MdWorkshop(code="WS-01", name="一号精密加工车间",
                          location="厦门集美区灌口工业区 3 号厂房",
                          manager="张建国", capacity_per_day=1200)
    db.add(workshop)
    db.flush()

    line_a = MdProductionLine(code="LINE-A", name="齿轮箱装配线", workshop_id=workshop.id,
                              capacity_per_hour=50)
    line_b = MdProductionLine(code="LINE-B", name="通用件加工线", workshop_id=workshop.id,
                              capacity_per_hour=65)
    db.add_all([line_a, line_b])
    db.flush()

    wh_raw = MdWarehouse(code="WH-RAW", name="原材料仓", category="RAW",
                         workshop_id=workshop.id)
    wh_wip = MdWarehouse(code="WH-WIP", name="线边库", category="WIP",
                         workshop_id=workshop.id)
    wh_fg = MdWarehouse(code="WH-FG", name="成品仓", category="FG",
                        workshop_id=workshop.id)
    db.add_all([wh_raw, wh_wip, wh_fg])
    db.flush()

    shift_day = MdShift(code="SHIFT-A", name="白班", start_time="08:00:00",
                        end_time="20:00:00", duration_hour=12.0)
    shift_night = MdShift(code="SHIFT-B", name="夜班", start_time="20:00:00",
                          end_time="08:00:00", duration_hour=12.0)
    db.add_all([shift_day, shift_night])

    for emp in EMPLOYEES:
        db.add(MdEmployee(emp_no=emp["emp_no"], name=emp["name"],
                          workshop_id=workshop.id, position=emp["position"],
                          hire_date=datetime(2024, 3, 1).date(), status=1))
    db.flush()

    line_map = {"LINE-A": line_a.id, "LINE-B": line_b.id}
    equip_map = {}
    for equip in EQUIPMENT:
        entity = MdEquipment(
            code=equip["code"], name=equip["name"], model=equip["model"],
            workshop_id=workshop.id, line_id=line_map[equip["line"]],
            supplier_id=supplier.id, status="IDLE",
            rated_speed=equip["rated_speed"], rated_output=equip["rated_output"],
            purchase_date=datetime(2023, 6, 15).date(),
        )
        db.add(entity)
        db.flush()
        equip_map[equip["code"]] = entity
    stats["equipment"] = len(EQUIPMENT)

    material_map = {}
    for item in MATERIALS:
        material = MmMaterial(code=item["code"], name=item["name"], spec=item["spec"],
                              unit=item["unit"], category=item["category"],
                              supplier_id=supplier2.id, unit_price=item["unit_price"],
                              safety_stock=item["safety_stock"], status=1)
        db.add(material)
        db.flush()
        material_map[item["code"]] = material
        # 初始库存（可直接用于工单领料）
        db.add(MmInventoryStock(material_id=material.id, warehouse_id=wh_raw.id,
                                qty_on_hand=item["init_qty"], qty_reserved=0.0))
    # 一颗低于安全库存的物料，用于演示预警
    low = material_map["RM-OILSEAL"]
    db.add(MmInventoryStock(material_id=low.id, warehouse_id=wh_wip.id,
                            qty_on_hand=120.0, qty_reserved=0.0))

    for product_spec in PRODUCTS:
        product = MdProduct(code=product_spec["code"], name=product_spec["name"],
                            spec=product_spec["spec"], unit=product_spec["unit"],
                            version="V1.0", std_cycle_sec=product_spec["std_cycle_sec"],
                            status=1)
        db.add(product)
        db.flush()

        routing = MdRouting(routing_code=f"RT-{product.code}",
                            routing_name=f"{product.name}标准工艺路线",
                            product_id=product.id, version="V1.0", status=1)
        db.add(routing)
        db.flush()

        for idx, template in enumerate(OPERATION_TEMPLATE[:product_spec["cycle"]], start=1):
            db.add(MdRoutingOperation(
                routing_id=routing.id, seq=idx * 10,
                operation_code=template["code"], operation_name=template["name"],
                default_equipment_id=_pick_equipment(equip_map, idx),
                std_time_sec=template["std_time_sec"],
                setup_time_sec=template["setup_time_sec"],
                qc_required=template["qc_required"],
                spc_enabled=template["spc_enabled"],
                spc_feature_name=template.get("feature", ""),
                spc_nominal=template.get("nominal", 0.0),
                spc_upper=template.get("upper", 0.0),
                spc_lower=template.get("lower", 0.0),
                spc_subgroup_size=5,
            ))

        bom = MdBom(bom_code=product_spec["bom_code"], product_id=product.id,
                    version="V1.0", status=1)
        db.add(bom)
        db.flush()
        for mat_code, qty_per_unit, loss_rate in BOM_MAPPING[product.code]:
            db.add(MdBomItem(bom_id=bom.id, material_id=material_map[mat_code].id,
                             qty_per_unit=qty_per_unit, loss_rate=loss_rate,
                             position="MAIN"))
    db.flush()

    for item in DEFECT_TYPES:
        db.add(QmDefectType(code=item["code"], name=item["name"],
                            category=item["category"], severity=item["severity"]))

    # 成品作为物料进入库存（用于完工入库）
    for product_spec in PRODUCTS:
        material = MmMaterial(code=product_spec["code"], name=product_spec["name"],
                              spec=product_spec["spec"], unit=product_spec["unit"],
                              category="FG", unit_price=0.0, safety_stock=0.0, status=1)
        db.add(material)
        db.flush()
        db.add(MmInventoryStock(material_id=material.id, warehouse_id=wh_fg.id,
                                qty_on_hand=0.0))

    db.commit()
    stats.update({"workshop": 1, "lines": 2, "warehouses": 3,
                  "materials": len(MATERIALS) + len(PRODUCTS),
                  "products": len(PRODUCTS), "employees": len(EMPLOYEES)})
    return stats


def _pick_equipment(equip_map: dict, seq: int) -> int:
    """按工序序号轮换绑定设备，让不同工序落在不同设备上。"""
    ordered = sorted(equip_map.values(), key=lambda x: x.code)
    return ordered[(seq - 1) % len(ordered)].id


# ===========================================================================
# 演示业务数据
# ===========================================================================
def seed_demo_orders(db, *, days: int = 30, count: int = 18) -> dict:
    """生成历史工单 + 报工 + SPC 子组 + 质检记录。"""
    existing = db.execute(select(func.count(PpWorkOrder.id))).scalar_one()
    if existing > 0:
        return {"skipped": True, "existing": existing}

    products = list(db.execute(select(MdProduct)).scalars().all())
    routings = {r.product_id: r for r in db.execute(select(MdRouting)).scalars().all()}
    employees = list(db.execute(select(MdEmployee)).scalars().all())
    shifts = list(db.execute(select(MdShift)).scalars().all())
    operations = list(db.execute(select(MdRoutingOperation)).scalars().all())
    _ = operations  # 工序展开由 OrderService 依据路线完成

    stats = {"created": 0, "reported": 0, "subgroups": 0, "tasks": 0}
    order_service = OrderService(db)

    for i in range(count):
        product = products[i % len(products)]
        routing = routings[product.id]
        created_at = datetime.now() - timedelta(days=RNG.randint(0, days))
        qty = RNG.choice([200, 300, 400, 500, 600])

        with db.begin_nested():
            order = order_service.create_order(
                product_id=product.id,
                routing_id=routing.id,
                qty_planned=qty,
                priority=RNG.randint(1, 7),
                plan_start=created_at,
                plan_end=created_at + timedelta(days=RNG.randint(2, 6)),
                owner_group=RNG.choice(["甲班", "乙班"]),
                operator="system-seed",
            )
            order.created_at = created_at
            order.actual_start = created_at
        db.flush()

        plan = _target_plan(i, count)
        outcome = _simulate_order_lifecycle(db, order, employees, shifts,
                                            created_at, plan)
        stats["created"] += 1
        stats["reported"] += outcome["reports"]
        db.commit()

    db.commit()

    # SPC 历史子组：让控制图一上来就有 25+ 组数据
    stats["subgroups"] = _seed_spc_history(db)

    # 质检历史记录（用于不良柏拉图）
    stats["tasks"] = _seed_inspection_history(db)

    db.commit()
    return stats


def _target_plan(index: int, total: int) -> str:
    """规划每张工单的终态，保证数据集覆盖所有状态。"""
    if index < total - 8:
        return "COMPLETED"
    if index < total - 5:
        return "IN_PROGRESS"
    if index < total - 3:
        return "RELEASED"
    if index == total - 3:
        return "PAUSED"
    if index == total - 2:
        return "CANCELLED"
    return "DRAFT"


def _simulate_order_lifecycle(db, order: PpWorkOrder, employees: list,
                              shifts: list, created_at: datetime, target: str) -> dict:
    """按目标终态推进工单，产出报工与若干不良。"""
    service = OrderService(db)
    result = {"reports": 0}

    if target == "DRAFT":
        return result
    if target == "CANCELLED":
        order.status = WorkOrderStatus.CANCELLED.value
        order.remark = "废单：客户订单变更"
        db.flush()
        return result

    service.transition(order.id, WorkOrderStatus.RELEASED.value, "admin")
    if target == "RELEASED":
        return result

    service.transition(order.id, WorkOrderStatus.IN_PROGRESS.value, "admin")

    ops = list(db.execute(
        select(PpWorkOrderOperation)
        .where(PpWorkOrderOperation.work_order_id == order.id)
        .order_by(PpWorkOrderOperation.seq.asc())
    ).scalars().all())

    # PAUSED 工单只推进到一半
    limit_ratio = 0.4 if target == "PAUSED" else (0.75 if target == "IN_PROGRESS" else 1.0)

    for op in ops:
        target_qty = int(op.plan_qty * limit_ratio)
        if target_qty <= 0:
            break
        batch = max(target_qty // RNG.randint(2, 3), 1)
        done = 0
        while done < target_qty:
            qty = min(batch, target_qty - done)
            good = int(qty * RNG.uniform(0.965, 0.998))
            defect = qty - good
            if good <= 0:
                good, defect = qty, 0
            report_time = created_at + timedelta(hours=RNG.randint(1, 72))
            try:
                service.report_work(
                    work_order_id=order.id,
                    operation_id=op.id,
                    qty_good=good,
                    qty_defect=defect,
                    employee_id=RNG.choice(employees).id,
                    shift_id=RNG.choice(shifts).id,
                    operator="system-seed",
                    idempotency_key=f"seed-{order.id}-{op.id}-{done}",
                )
            except Exception as exc:  # 终态工单不再接受报工，直接跳出
                db.rollback()
                break
            _retime_report(db, order.id, op.id, report_time)
            done += qty
            result["reports"] += 1
        if target == "PAUSED":
            break

    if target == "PAUSED":
        try:
            service.transition(order.id, WorkOrderStatus.PAUSED.value, "admin",
                               reason="设备维保，暂停生产")
        except Exception:
            db.rollback()
    elif target == "COMPLETED":
        # 补齐剩余量，确保能走到完工
        _complete_remaining(db, order, employees, shifts, created_at, service)
        try:
            service.transition(order.id, WorkOrderStatus.COMPLETED.value, "admin")
        except Exception:
            db.rollback()
    return result


def _retime_report(db, order_id: int, operation_id: int, report_time: datetime) -> None:
    """把最近一笔报工的时间改写到过去，让产量报表有按天的数据分布。"""
    report = db.execute(
        select(PpWorkReport)
        .where(PpWorkReport.work_order_id == order_id,
               PpWorkReport.operation_id == operation_id)
        .order_by(PpWorkReport.id.desc())
        .limit(1)
    ).scalars().first()
    if report is not None:
        report.report_time = report_time
        db.flush()


def _complete_remaining(db, order: PpWorkOrder, employees: list, shifts: list,
                        created_at: datetime, service: OrderService) -> None:
    """把剩余工序一次性报满，让工单达到可完工状态。"""
    ops = list(db.execute(
        select(PpWorkOrderOperation)
        .where(PpWorkOrderOperation.work_order_id == order.id,
               PpWorkOrderOperation.status != OperationStatus.FINISHED.value)
        .order_by(PpWorkOrderOperation.seq.asc())
    ).scalars().all())
    for op in ops:
        remain = int(op.plan_qty) - int(op.done_qty)
        if remain <= 0:
            continue
        good = int(remain * RNG.uniform(0.96, 0.995))
        defect = remain - good
        try:
            service.report_work(
                work_order_id=order.id, operation_id=op.id,
                qty_good=good, qty_defect=defect,
                employee_id=RNG.choice(employees).id,
                shift_id=RNG.choice(shifts).id,
                operator="system-seed",
                idempotency_key=f"seed-final-{order.id}-{op.id}",
            )
        except Exception:
            db.rollback()
            continue
        _retime_report(db, order.id, op.id,
                       created_at + timedelta(hours=RNG.randint(24, 96)))


def _seed_spc_history(db) -> int:
    """生成 SPC 历史子组，并刻意注入 3 组超限批次。- 用于演示告警链路。"""
    spc_ops = list(db.execute(
        select(MdRoutingOperation).where(MdRoutingOperation.spc_enabled.is_(True))
    ).scalars().all())
    if not spc_ops:
        return 0

    from app.services.spc_service import SPCService

    service = SPCService(db)
    total = 0
    for src in spc_ops:
        base = float(src.spc_nominal or 40.0)
        tolerance = (float(src.spc_upper or base + 0.05) - base) / 2
        for idx in range(1, 27):
            # 第 12、21、25 组注入异常：整体偏移 + 偶发超规格
            if idx in (12, 21, 25):
                drift = tolerance * RNG.uniform(2.2, 3.2)
            elif idx > 18:
                drift = tolerance * RNG.uniform(0.2, 0.6)
            else:
                drift = 0.0
            values = [
                round(base + drift + RNG.gauss(0, tolerance / 3), 4)
                for _ in range(src.spc_subgroup_size)
            ]
            service.record_subgroup(
                product_id=src.routing_id and _product_of_routing(db, src.routing_id),
                operation_code=src.operation_code,
                values=values,
                feature_name=src.spc_feature_name,
                nominal=base,
                upper_spec=float(src.spc_upper or 0),
                lower_spec=float(src.spc_lower or 0),
                sample_time=datetime.now() - timedelta(hours=(27 - idx) * 2),
            )
            total += 1
    db.commit()
    return total


def _product_of_routing(db, routing_id: int) -> int:
    routing = db.get(MdRouting, routing_id)
    return int(routing.product_id)


def _seed_inspection_history(db) -> int:
    """生成历史质检单与检验记录，供不良柏拉图分析。"""
    defect_types = list(db.execute(select(QmDefectType)).scalars().all())
    products = list(db.execute(select(MdProduct)).scalars().all())
    orders = list(db.execute(
        select(PpWorkOrder).order_by(PpWorkOrder.id.desc()).limit(6)
    ).scalars().all())
    if not defect_types or not orders:
        return 0

    service = QualityService(db)
    created = 0
    for order in orders:
        task = service.create_manual(
            product_id=order.product_id,
            work_order_id=order.id,
            sample_qty=10,
            inspector_no="EMP004",
            reason="成品抽检",
        )
        service.transition(task.id, InspectionStatus.TESTING.value, "EMP004")
        upper, lower = _tolerance_of(defect_types, order.product_id, products)
        for seq in range(1, 11):
            # 大约 12% 的不良率
            if RNG.random() < 0.12:
                defect = RNG.choice(defect_types)
                value = upper + 0.05 if RNG.random() < 0.5 else lower - 0.05
            else:
                defect = None
                value = RNG.uniform(lower + 0.005, upper - 0.005)
            service.add_record(
                task_id=task.id, seq=seq, measured_value=round(value, 4),
                nominal=(upper + lower) / 2, tolerance_upper=upper,
                tolerance_lower=lower,
                defect_type_id=defect.id if defect else None,
                feature_name="装配间隙",
            )
        target = (InspectionStatus.FAILED.value
                  if int(task.defect_qty or 0) > 0 else InspectionStatus.PASSED.value)
        service.transition(task.id, target, "EMP004")
        service.transition(task.id, InspectionStatus.CLOSED.value, "EMP004")
        created += 1
    db.commit()
    return created


def _tolerance_of(defect_types, product_id: int, products: list) -> tuple[float, float]:
    product = next((p for p in products if p.id == product_id), None)
    base = float(product.std_cycle_sec or 100) / 100 if product else 10.0
    return base + 0.05, base - 0.05


# ===========================================================================
# 入口
# ===========================================================================
def run(*, reset: bool = False, gateway_frames: int = 0) -> dict:
    """执行完整播种流程。"""
    if reset:
        init_db(drop_first=True)
    else:
        init_db()

    db = SessionLocal()
    summary: dict = {"tables": count_tables(), "db_engine": settings.DB_ENGINE}
    try:
        summary["rbac"] = AuthService(db).ensure_default_rbac()
        db.commit()
        summary["master"] = seed_master_data(db)
        summary["demo"] = seed_demo_orders(db)
        if gateway_frames:
            from app.realtime.device_gateway import DeviceGateway

            gateway = DeviceGateway(write_db=True)
            for _ in range(gateway_frames):
                gateway.tick()
            summary["gateway_frames"] = gateway_frames
    finally:
        db.close()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="MES 示例数据播种脚本")
    parser.add_argument("--reset", action="store_true", help="删库重建后再播种")
    parser.add_argument("--gateway", type=int, default=0,
                        help="额外触发数采网关的采集帧数")
    args = parser.parse_args()

    summary = run(reset=args.reset, gateway_frames=args.gateway)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
