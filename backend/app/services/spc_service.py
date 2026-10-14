"""SPC 业务服务：把 :mod:`app.services.spc_core` 的纯算法接到业务链路上。

链路闭环（对应简历「质量模块」描述）::

    报工/抽检采样子组 → 计算控制限 → 判异检测
        → 命中准则 → 标记子组异常 → 自动生成「待处理」质检单 → 看板告警

对外提供：

* :meth:`SPCService.record_subgroup`    录入一个子组样本（含判异与告警联动）
* :meth:`SPCService.get_control_chart`  输出 ECharts 可直接消费的控制图数据
* :meth:`SPCService.analyze_series`     仅做分析，不落库（供预演与测试）
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.quality import QmSpcSubgroup
from app.services.quality_service import QualityService
from app.services.spc_core import (
    RULE_DESCRIPTIONS,
    SpcAnalysis,
    analyze,
    subgroup_mean,
    subgroup_range,
    validate_subgroup,
)
from app.utils import next_no


def _enabled_rules() -> set[str]:
    raw = settings.SPC_RULE_SET
    rules = {item.strip().upper() for item in raw.split(",") if item.strip()}
    # 准则 1（超出控制限）是控制图的底线，始终启用
    rules.add("RULE1")
    return rules


class SPCService:
    """SPC 控制图与超异常联动。"""

    def __init__(self, db: Session):
        self.db = db
        self.quality = QualityService(db)

    # ---------------------------------------------------------------- 录入子组
    def record_subgroup(
        self,
        *,
        product_id: int,
        operation_code: str,
        values: list[float],
        feature_name: str = "",
        work_order_id: int | None = None,
        operation_id: int | None = None,
        nominal: float = 0.0,
        upper_spec: float = 0.0,
        lower_spec: float = 0.0,
        sample_time: datetime | None = None,
    ) -> dict:
        """采集一个子组并完成判异闭环。

        :return: 含子组信息、控制限、命中判异准则、是否生成质检单的结果字典
        """
        validate_subgroup(values)

        seq = self._next_subgroup_no(product_id, operation_code)
        mean_v = subgroup_mean(values)
        range_v = subgroup_range(values)

        subgroup = QmSpcSubgroup(
            work_order_id=work_order_id,
            operation_id=operation_id,
            product_id=product_id,
            operation_code=operation_code,
            feature_name=feature_name or "关键尺寸",
            subgroup_no=seq,
            subgroup_size=len(values),
            sample_values=json.dumps([round(float(v), 4) for v in values]),
            mean_value=round(mean_v, 4),
            range_value=round(range_v, 4),
            nominal=nominal,
            upper_spec=upper_spec,
            lower_spec=lower_spec,
            sample_time=sample_time or datetime.now(),
        )
        self.db.add(subgroup)
        self.db.flush()

        # 以「该 产品+工序」的历史全部子组重算控制限（滚动基准）
        result = self._analyze_series(product_id, operation_code)
        hit_rules = result.violation_point_indexes

        subgroup.is_out_of_control = (seq - 1) in hit_rules
        if subgroup.is_out_of_control:
            rules_now = sorted({v["rule"] for v in result.violations if v["index"] == seq - 1})
            subgroup.alarm_rules = ",".join(rules_now)
            task = self.quality.create_from_spc_alert(
                subgroup=subgroup,
                rules=rules_now,
                mean_value=mean_v,
                product_id=product_id,
                work_order_id=work_order_id,
                operation_id=operation_id,
            )
            task.spc_subgroup_id = subgroup.id
        self.db.flush()

        return {
            "subgroup_id": subgroup.id,
            "subgroup_no": seq,
            "mean_value": float(subgroup.mean_value),
            "range_value": float(subgroup.range_value),
            "is_out_of_control": subgroup.is_out_of_control,
            "alarm_rules": subgroup.alarm_rules,
            "inspection_task_no": None if not subgroup.is_out_of_control else task.task_no,
            "limits": self._limits_payload(result),
            "violations": result.violations,
        }

    # ---------------------------------------------------------------- 控制图
    def get_control_chart(
        self, product_id: int, operation_code: str, tail: int = 30
    ) -> dict:
        """按「产品 + 工序」取最近 `tail` 个子组，输出控制图数据。

        返回结构已包含 ECharts 所需的 markLine 数据（中心线 / 上下控制限），
        前端无需再做任何统计计算。
        """
        result, subgroups = self._tail_analysis(product_id, operation_code, tail)
        if not subgroups:
            raise NotFoundError("该「产品 + 工序」尚无任何 SPC 数据")

        return {
            "feature_name": subgroups[0].feature_name,
            "operation_code": operation_code,
            "subgroup_nos": [item.subgroup_no for item in subgroups],
            "sample_values": [json.loads(item.sample_values) for item in subgroups],
            "means": result.means,
            "ranges": result.ranges,
            "limits": self._limits_payload(result),
            "violations": result.violations,
            "out_of_control_indexes": sorted(result.violation_point_indexes),
            "totals": {
                "subgroups": len(subgroups),
                "out_of_control": sum(1 for s in subgroups if s.is_out_of_control),
            },
        }

    def analyze_series(self, samples: list[list[float]], upper_spec: float = 0.0,
                       lower_spec: float = 0.0) -> SpcAnalysis:
        """纯计算入口（不落库），供 API 预演与单元测试复用。"""
        return analyze(samples, upper_spec=upper_spec, lower_spec=lower_spec,
                       enabled_rules=_enabled_rules())

    # ---------------------------------------------------------------- 内部方法
    def _next_subgroup_no(self, product_id: int, operation_code: str) -> int:
        stmt = (
            select(QmSpcSubgroup.subgroup_no)
            .where(
                QmSpcSubgroup.product_id == product_id,
                QmSpcSubgroup.operation_code == operation_code,
            )
            .order_by(QmSpcSubgroup.subgroup_no.desc())
            .limit(1)
        )
        last = self.db.execute(stmt).scalar()
        return (last or 0) + 1

    def _series(self, product_id: int, operation_code: str,
                tail: int | None = None) -> list[QmSpcSubgroup]:
        stmt = (
            select(QmSpcSubgroup)
            .where(
                QmSpcSubgroup.product_id == product_id,
                QmSpcSubgroup.operation_code == operation_code,
            )
            .order_by(QmSpcSubgroup.subgroup_no.asc())
        )
        rows = list(self.db.execute(stmt).scalars().all())
        return rows[-tail:] if tail else rows

    def _tail_analysis(self, product_id: int, operation_code: str,
                       tail: int | None) -> tuple[SpcAnalysis, list[QmSpcSubgroup]]:
        subgroups = self._series(product_id, operation_code, tail=tail)
        if not subgroups:
            raise NotFoundError("该「产品 + 工序」尚无任何 SPC 数据")
        samples = [json.loads(item.sample_values) for item in subgroups]
        upper = float(subgroups[-1].upper_spec or 0)
        lower = float(subgroups[-1].lower_spec or 0)
        result = analyze(samples, upper_spec=upper, lower_spec=lower,
                         enabled_rules=_enabled_rules())
        return result, subgroups

    def _analyze_series(self, product_id: int, operation_code: str) -> SpcAnalysis:
        """基于该「产品 + 工序」的全部历史子组重算控制限。"""
        result, _ = self._tail_analysis(product_id, operation_code, tail=None)
        return result

    @staticmethod
    def _limits_payload(result: SpcAnalysis) -> dict:
        limits = result.limits
        return {
            "subgroup_size": limits.subgroup_size,
            "subgroups": limits.subgroups,
            "xbar_center": round(limits.xbar_center, 4),
            "r_center": round(limits.r_center, 4),
            "xbar_ucl": round(limits.xbar_ucl, 4),
            "xbar_lcl": round(limits.xbar_lcl, 4),
            "r_ucl": round(limits.r_ucl, 4),
            "r_lcl": round(limits.r_lcl, 4),
            "sigma_hat": round(limits.sigma_hat, 4),
            "cp": round(limits.cp, 3),
            "cpk": round(limits.cpk, 3),
            "is_established": limits.is_established,
            "message": limits.message,
        }

    @staticmethod
    def rule_descriptions() -> dict[str, str]:
        return dict(RULE_DESCRIPTIONS)


def default_inspection_no() -> str:
    """质检单号工具（供其他服务复用）。"""
    return next_no("QC")
