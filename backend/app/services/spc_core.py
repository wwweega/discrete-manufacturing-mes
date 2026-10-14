"""SPC 统计过程控制：X̄-R（均值-极差）控制图核心算法。

全部纯函数实现，**不依赖数据库与 FastAPI**，便于单元测试直接覆盖。

控制图原理
----------
对 m 个子组（每组 n 件样本）：

* 第 i 组均值  X̄ᵢ = Σx / n
* 第 i 组极差  Rᵢ  = max(x) − min(x)
* 中心线
    - X̄ 图：CL = X̄̄ = ΣX̄ᵢ / m
    - R  图：CL = R̄  = ΣRᵢ  / m
* 控制限（变异用组内极差估计，无需额外给 σ）
    - X̄ 图：UCL = X̄̄ + A₂·R̄，LCL = X̄̄ − A₂·R̄
    - R  图：UCL = D₄·R̄，LCL = D₃·R̄

  A₂/D₃/D₄ 为标准计量控制图系数，取值见 :data:`CONTROL_CHART_CONSTANTS`。

过程能力
--------
组内标准差估计 σ̂ = R̄ / d₂，据此计算 Cp / Cpk，判断过程是否满足公差要求。

判异准则
--------
实现 GB/T 4091（等同 ISO 8258 / Western Electric）全部 8 条，
命中即标记批次异常并触发后续动作（自动生成待处理质检单）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.base import StrEnum

# ---------------------------------------------------------------------------
# 标准系数表：n 为子组容量
# ---------------------------------------------------------------------------
CONTROL_CHART_CONSTANTS: dict[int, dict[str, float]] = {
    2: {"A2": 1.880, "D3": 0.000, "D4": 3.267, "d2": 1.128},
    3: {"A2": 1.023, "D3": 0.000, "D4": 2.574, "d2": 1.693},
    4: {"A2": 0.729, "D3": 0.000, "D4": 2.282, "d2": 2.059},
    5: {"A2": 0.577, "D3": 0.000, "D4": 2.114, "d2": 2.326},
    6: {"A2": 0.483, "D3": 0.000, "D4": 2.004, "d2": 2.534},
    7: {"A2": 0.419, "D3": 0.076, "D4": 1.924, "d2": 2.704},
    8: {"A2": 0.373, "D3": 0.136, "D4": 1.864, "d2": 2.847},
    9: {"A2": 0.337, "D3": 0.184, "D4": 1.816, "d2": 2.970},
    10: {"A2": 0.308, "D3": 0.223, "D4": 1.777, "d2": 3.078},
}

MIN_SUBGROUP_SIZE = 2
MAX_SUBGROUP_SIZE = 10
#: 建立控制限所需的最少子组数（实践中多取 20~25 组）
MIN_SUBGROUPS_FOR_LIMIT = 5


class SpcRule(StrEnum):
    """8 条判异准则。"""

    RULE1 = "RULE1"  # 1 点超出控制限
    RULE2 = "RULE2"  # 连续 9 点位于中心线同侧
    RULE3 = "RULE3"  # 连续 6 点递增或递减
    RULE4 = "RULE4"  # 连续 14 点相邻交替上下
    RULE5 = "RULE5"  # 连续 3 点中有 2 点落在同侧 A 区（2σ~3σ）
    RULE6 = "RULE6"  # 连续 5 点中有 4 点落在同侧 B 区以外（1σ~3σ）
    RULE7 = "RULE7"  # 连续 15 点落在中心线两侧 C 区（±1σ）内
    RULE8 = "RULE8"  # 连续 8 点无 1 点落在 C 区内

    @property
    def description(self) -> str:
        return RULE_DESCRIPTIONS[self.value]


RULE_DESCRIPTIONS: dict[str, str] = {
    "RULE1": "1 点超出控制限（超出 ±3σ）",
    "RULE2": "连续 9 点位于中心线同侧",
    "RULE3": "连续 6 点持续上升或下降",
    "RULE4": "连续 14 点相邻点交替上下",
    "RULE5": "连续 3 点中有 2 点落在中心线同侧 A 区（2σ~3σ）",
    "RULE6": "连续 5 点中有 4 点落在中心线同侧 B 区以外（>1σ）",
    "RULE7": "连续 15 点落在中心线两侧 C 区（±1σ）内",
    "RULE8": "连续 8 点落在中心线两侧但均在 ±1σ 以外",
}


class SpcCalculationError(ValueError):
    """SPC 计算输入非法。"""


# ---------------------------------------------------------------------------
# 基础统计
# ---------------------------------------------------------------------------
def subgroup_mean(values: list[float]) -> float:
    """子组均值。"""
    if not values:
        raise SpcCalculationError("样本值不可为空")
    return sum(values) / len(values)


def subgroup_range(values: list[float]) -> float:
    """子组极差。"""
    if not values:
        raise SpcCalculationError("样本值不可为空")
    return max(values) - min(values)


def validate_subgroup(values: list[float], size: int | None = None) -> None:
    """校验单个子组的合法性。"""
    if not values:
        raise SpcCalculationError("子组样本不能为空")
    if size is not None and len(values) != size:
        raise SpcCalculationError(f"子组容量应为 {size}，实际 {len(values)}")
    if len(values) < MIN_SUBGROUP_SIZE:
        raise SpcCalculationError(f"子组容量至少为 {MIN_SUBGROUP_SIZE}")
    if len(values) > MAX_SUBGROUP_SIZE:
        raise SpcCalculationError(f"子组容量最多为 {MAX_SUBGROUP_SIZE}")


# ---------------------------------------------------------------------------
# 控制限
# ---------------------------------------------------------------------------
@dataclass
class ControlLimits:
    """X̄ 图与 R 图的中心线与控制限。"""

    subgroup_size: int
    subgroups: int
    xbar_center: float
    r_center: float
    xbar_ucl: float
    xbar_lcl: float
    r_ucl: float
    r_lcl: float
    sigma_hat: float        # 组内标准差估计 R̄/d₂
    cp: float = 0.0
    cpk: float = 0.0
    is_established: bool = True
    message: str = ""

    @property
    def xbar_sigma(self) -> float:
        """X̄ 分布的标准差：(UCL − CL) / 3，用于划分 A/B/C 区。"""
        return (self.xbar_ucl - self.xbar_center) / 3 if self.xbar_ucl != self.xbar_center else 0.0


def constants_for(size: int) -> dict[str, float]:
    """取子组容量对应的系数。"""
    if size not in CONTROL_CHART_CONSTANTS:
        raise SpcCalculationError(
            f"不支持的子组容量 n={size}，支持范围 {MIN_SUBGROUP_SIZE}~{MAX_SUBGROUP_SIZE}"
        )
    return CONTROL_CHART_CONSTANTS[size]


def compute_control_limits(
    samples: list[list[float]],
    *,
    upper_spec: float = 0.0,
    lower_spec: float = 0.0,
) -> ControlLimits:
    """由二维样本数据计算控制限。

    :param samples: ``[[x11, x12, ...], [x21, x22, ...]]`` 每个内层列表为一个子组
    :param upper_spec: 规格上限 USL，非 0 时计算 Cp/Cpk
    :param lower_spec: 规格下限 LSL
    """
    if not samples:
        raise SpcCalculationError("至少需要 1 个子组")

    size = len(samples[0])
    for idx, values in enumerate(samples, start=1):
        validate_subgroup(values, size)

    means = [subgroup_mean(v) for v in samples]
    ranges = [subgroup_range(v) for v in samples]

    xbar_bar = sum(means) / len(means)
    r_bar = sum(ranges) / len(ranges)

    coef = constants_for(size)
    sigma_hat = r_bar / coef["d2"]

    limits = ControlLimits(
        subgroup_size=size,
        subgroups=len(samples),
        xbar_center=xbar_bar,
        r_center=r_bar,
        xbar_ucl=xbar_bar + coef["A2"] * r_bar,
        xbar_lcl=xbar_bar - coef["A2"] * r_bar,
        r_ucl=coef["D4"] * r_bar,
        r_lcl=coef["D3"] * r_bar,
        sigma_hat=sigma_hat,
    )

    if len(samples) < MIN_SUBGROUPS_FOR_LIMIT:
        limits.is_established = False
        limits.message = (
            f"当前仅 {len(samples)} 个子组，少于分析用下限 {MIN_SUBGROUPS_FOR_LIMIT} 组，"
            "控制限仅供参考"
        )

    if upper_spec > lower_spec and sigma_hat > 0:
        limits.cp = (upper_spec - lower_spec) / (6 * sigma_hat)
        limits.cpk = min(
            upper_spec - xbar_bar, xbar_bar - lower_spec
        ) / (3 * sigma_hat)
    return limits


# ---------------------------------------------------------------------------
# 判异准则
# ---------------------------------------------------------------------------
def _zone_of(value: float, center: float, sigma: float) -> int:
    """返回值所在区域：0=C区(|z|<=1) 1=B区(1<|z|<=2) 2=A区(2<|z|<=3) 3=超限。"""
    if sigma == 0:
        return 0
    z = abs(value - center) / sigma
    if z <= 1:
        return 0
    if z <= 2:
        return 1
    if z <= 3:
        return 2
    return 3


def detect_violations(
    means: list[float],
    ranges: list[float],
    limits: ControlLimits,
    enabled_rules: set[str] | None = None,
) -> list[dict]:
    """对均值序列执行 8 条判异准则。

    :return: 命中记录列表，元素形如
        ``{"index": int, "rule": str, "description": str, "value": float}``
    """
    enabled = enabled_rules or set(RULE_DESCRIPTIONS.keys())
    sigma = limits.xbar_sigma
    center = limits.xbar_center
    violations: list[dict] = []

    # ---- 准则 1：超出控制限（含 R 图超限）----
    if "RULE1" in enabled:
        for i, value in enumerate(means):
            if value > limits.xbar_ucl or value < limits.xbar_lcl:
                violations.append(_violation(i, "RULE1", value))
        for i, value in enumerate(ranges):
            if value > limits.r_ucl or (limits.r_lcl > 0 and value < limits.r_lcl):
                violations.append(_violation(i, "RULE1", value, chart="R"))

    if len(means) < 2:
        return violations

    signs = [1 if v > center else (-1 if v < center else 0) for v in means]

    # ---- 准则 2：连续 9 点位于中心线同侧 ----
    if "RULE2" in enabled:
        violations.extend(_run_of_same_sign(signs, means, length=9, rule="RULE2"))

    # ---- 准则 3：连续 6 点持续上升或下降 ----
    if "RULE3" in enabled:
        run, direction = 1, 0
        for i in range(1, len(means)):
            step = (means[i] > means[i - 1]) - (means[i] < means[i - 1])
            if step != 0 and step == direction:
                run += 1
            else:
                run, direction = 2 if step != 0 else 1, step
            if run >= 6:
                violations.append(_violation(i, "RULE3", means[i]))

    # ---- 准则 4：连续 14 点相邻交替上下 ----
    if "RULE4" in enabled:
        alternating = 1
        for i in range(1, len(means)):
            if i >= 2:
                up = means[i] > means[i - 1]
                prev_up = means[i - 1] > means[i - 2]
                alternating = alternating + 1 if up != prev_up else 1
            else:
                alternating = 2
            if alternating >= 14:
                violations.append(_violation(i, "RULE4", means[i]))

    zones = [_zone_of(v, center, sigma) for v in means]

    # ---- 准则 5：连续 3 点中有 2 点落在同侧 A 区 ----
    if "RULE5" in enabled:
        for i in range(2, len(means)):
            window = list(zip(signs[i - 2: i + 1], zones[i - 2: i + 1]))
            hits = [item for item in window if item[1] >= 2 and item[0] == signs[i] and item[0] != 0]
            if len(hits) >= 2:
                violations.append(_violation(i, "RULE5", means[i]))

    # ---- 准则 6：连续 5 点中有 4 点落在同侧 1σ 以外 ----
    if "RULE6" in enabled:
        for i in range(4, len(means)):
            window = list(zip(signs[i - 4: i + 1], zones[i - 4: i + 1]))
            hits = [item for item in window if item[1] >= 1 and item[0] == signs[i] and item[0] != 0]
            if len(hits) >= 4:
                violations.append(_violation(i, "RULE6", means[i]))

    # ---- 准则 7：连续 15 点位于 ±1σ 内 ----
    if "RULE7" in enabled:
        streak = 0
        for i, z in enumerate(zones):
            streak = streak + 1 if z == 0 else 0
            if streak >= 15:
                violations.append(_violation(i, "RULE7", means[i]))

    # ---- 准则 8：连续 8 点位于 ±1σ 外（两侧均有分布）----
    if "RULE8" in enabled:
        streak = 0
        for i, z in enumerate(zones):
            streak = streak + 1 if z >= 1 else 0
            if streak >= 8:
                violations.append(_violation(i, "RULE8", means[i]))

    return _dedup(violations)


def _violation(index: int, rule: str, value: float, chart: str = "XBAR") -> dict:
    return {
        "index": index,
        "subgroup_no": index + 1,
        "rule": rule,
        "description": RULE_DESCRIPTIONS[rule],
        "value": round(float(value), 4),
        "chart": chart,
    }


def _run_of_same_sign(
    signs: list[int], means: list[float], length: int, rule: str
) -> list[dict]:
    """检测连续 `length` 个点位于中心线同侧。"""
    result, streak, last = [], 0, 0
    for i, sign in enumerate(signs):
        if sign != 0 and sign == last:
            streak += 1
        else:
            streak = 1 if sign != 0 else 0
        last = sign
        if streak >= length:
            result.append(_violation(i, rule, means[i]))
    return result


def _dedup(items: list[dict]) -> list[dict]:
    """同一子组同一准则只保留一条记录。"""
    seen, unique = set(), []
    for item in items:
        key = (item["index"], item["rule"], item["chart"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return sorted(unique, key=lambda x: (x["index"], x["rule"]))


# ---------------------------------------------------------------------------
# 高层聚合：一次算出看板所需的全部数据
# ---------------------------------------------------------------------------
@dataclass
class SpcAnalysis:
    """控制图分析结果，直接映射到前端 ECharts 配置。"""

    limits: ControlLimits
    means: list[float]
    ranges: list[float]
    violations: list[dict]
    violation_point_indexes: set[int] = field(default_factory=set)

    @property
    def out_of_control(self) -> bool:
        return bool(self.violations)

    @property
    def violated_rules(self) -> list[str]:
        return sorted({item["rule"] for item in self.violations})


def analyze(samples: list[list[float]], *, upper_spec: float = 0.0,
            lower_spec: float = 0.0,
            enabled_rules: set[str] | None = None) -> SpcAnalysis:
    """一次性完成控制限计算 + 判异，返回可直接渲染的结果。"""
    limits = compute_control_limits(samples, upper_spec=upper_spec, lower_spec=lower_spec)
    means = [subgroup_mean(v) for v in samples]
    ranges = [subgroup_range(v) for v in samples]
    violations = detect_violations(means, ranges, limits, enabled_rules)
    return SpcAnalysis(
        limits=limits,
        means=[round(float(v), 4) for v in means],
        ranges=[round(float(v), 4) for v in ranges],
        violations=violations,
        violation_point_indexes={item["index"] for item in violations},
    )
