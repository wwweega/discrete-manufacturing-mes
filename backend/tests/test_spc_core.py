"""SPC X̄-R 控制图核心算法单测（纯函数，不依赖数据库）。"""

from __future__ import annotations

import pytest

from app.services.spc_core import (
    CONTROL_CHART_CONSTANTS,
    RULE_DESCRIPTIONS,
    SpcCalculationError,
    analyze,
    compute_control_limits,
    constants_for,
    detect_violations,
    subgroup_mean,
    subgroup_range,
    validate_subgroup,
)


def _samples(base: float = 40.0, sigma: float = 0.01, groups: int = 20,
             size: int = 5, seed: int = 42):
    """生成受控过程样本。"""
    import random

    rng = random.Random(seed)
    return [[round(base + rng.gauss(0, sigma), 4) for _ in range(size)]
            for _ in range(groups)]


# --------------------------------------------------------------------- 基础统计
def test_subgroup_mean_and_range():
    values = [10.0, 10.1, 9.9, 10.0, 10.05]
    assert subgroup_mean(values) == pytest.approx(10.01, abs=1e-6)
    assert subgroup_range(values) == pytest.approx(0.2, abs=1e-6)


def test_validate_subgroup_rejects_invalid_size():
    validate_subgroup([10.0, 10.1])
    validate_subgroup([10.0] * 10)
    with pytest.raises(SpcCalculationError):
        validate_subgroup([10.0])
    with pytest.raises(SpcCalculationError):
        validate_subgroup([10.0] * 11)
    with pytest.raises(SpcCalculationError):
        validate_subgroup([10.0, 10.1, 10.2], size=5)


def test_empty_samples_raises():
    with pytest.raises(SpcCalculationError):
        compute_control_limits([])


def test_constants_for_valid_range():
    assert constants_for(5)["A2"] == 0.577
    assert constants_for(5)["D4"] == 2.114
    assert constants_for(5)["d2"] == 2.326
    with pytest.raises(SpcCalculationError):
        constants_for(11)


# --------------------------------------------------------------------- 控制限
def test_control_limits_match_standard_formula():
    """UCL/LCL 必须与教科书公式 X̄̄ ± A₂·R̄ 完全一致。"""
    samples = _samples()
    limits = compute_control_limits(samples, upper_spec=40.05, lower_spec=39.95)

    assert limits.subgroup_size == 5
    assert limits.subgroups == 20

    means = [subgroup_mean(v) for v in samples]
    ranges = [subgroup_range(v) for v in samples]
    xbar_bar = sum(means) / len(means)
    r_bar = sum(ranges) / len(ranges)
    coef = CONTROL_CHART_CONSTANTS[5]

    assert limits.xbar_center == pytest.approx(xbar_bar, abs=1e-6)
    assert limits.r_center == pytest.approx(r_bar, abs=1e-6)
    assert limits.xbar_ucl == pytest.approx(xbar_bar + coef["A2"] * r_bar, abs=1e-6)
    assert limits.xbar_lcl == pytest.approx(xbar_bar - coef["A2"] * r_bar, abs=1e-6)
    assert limits.r_ucl == pytest.approx(coef["D4"] * r_bar, abs=1e-6)
    assert limits.r_lcl == pytest.approx(coef["D3"] * r_bar, abs=1e-6)


def test_control_limits_are_symmetric_around_center():
    limits = compute_control_limits(_samples())
    upper_distance = limits.xbar_ucl - limits.xbar_center
    lower_distance = limits.xbar_center - limits.xbar_lcl
    assert upper_distance == pytest.approx(lower_distance, abs=1e-9)


def test_sigma_estimation_and_capability_indices():
    """σ̂ = R̄/d₂，且 Cp/Cpk 由规格带宽度算出。"""
    samples = _samples(sigma=0.01)
    limits = compute_control_limits(samples, upper_spec=40.05, lower_spec=39.95)
    assert limits.sigma_hat > 0

    expected_cp = (40.05 - 39.95) / (6 * limits.sigma_hat)
    assert limits.cp == pytest.approx(expected_cp, rel=1e-3)
    assert limits.cpk <= limits.cp + 1e-9       # Cpk 恒不大于 Cp


def test_few_subgroups_marks_not_established():
    limits = compute_control_limits(_samples(groups=4))
    assert limits.is_established is False
    assert "控制限仅供参考" in limits.message


# --------------------------------------------------------------------- 判异准则
def test_rule1_detects_point_beyond_control_limit():
    samples = _samples()
    limits = compute_control_limits(samples)
    means = [subgroup_mean(v) for v in samples]
    ranges = [subgroup_range(v) for v in samples]

    # 人为把最后一组整体抬出上控制限
    means[-1] = limits.xbar_ucl + 0.05
    hits = detect_violations(means, ranges, limits, {"RULE1"})
    assert [h["index"] for h in hits] == [len(means) - 1]
    assert hits[0]["rule"] == "RULE1"


def test_rule2_detects_nine_points_one_side():
    limits = compute_control_limits(_samples(groups=9))
    means = [limits.xbar_center + 0.01] * 9        # 全部高于中心线
    ranges = [0.02] * 9
    hits = detect_violations(means, ranges, limits, {"RULE2"})
    assert len(hits) == 1
    assert hits[0]["index"] == 8


def test_rule3_detects_six_monotonic_points():
    limits = compute_control_limits(_samples(groups=6))
    means = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    ranges = [0.1] * 6
    hits = detect_violations(means, ranges, limits, {"RULE3"})
    assert len(hits) == 1 and hits[0]["index"] == 5


def test_rule4_detects_fourteen_alternating_points():
    means = [1.0, 3.0] * 7                          # 14 点交替
    limits = compute_control_limits(_samples(groups=14))
    hits = detect_violations(means, [0.1] * 14, limits, {"RULE4"})
    assert any(h["rule"] == "RULE4" for h in hits)


def test_rule_is_not_triggered_in_stable_process():
    """受控样本不应命中任何准则。"""
    result = analyze(_samples(sigma=0.01, groups=25))
    assert result.out_of_control is False
    assert result.violations == []


def test_analyze_reports_violations_and_limits():
    result = analyze(_samples(groups=25))
    assert len(result.means) == 25
    assert len(result.ranges) == 25
    assert result.limits.is_established is True
    assert isinstance(result.violated_rules, list)


def test_all_eight_rules_have_descriptions():
    assert len(RULE_DESCRIPTIONS) == 8
    for rule in ("RULE1", "RULE2", "RULE3", "RULE4",
                 "RULE5", "RULE6", "RULE7", "RULE8"):
        assert RULE_DESCRIPTIONS[rule]
