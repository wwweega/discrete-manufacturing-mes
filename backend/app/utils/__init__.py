"""通用工具：单号生成、时间处理、幂等指纹。"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

_CN_TZ = timezone(timedelta(hours=8))

# 单号内存序号，避免同一毫秒生成重复号
_SEQ = {"base": random.randint(1000, 9999)}


def next_no(prefix: str, width: int = 6) -> str:
    """生成带业务前缀的单号，如 `WO20260814000123`。

    格式：``<前缀><yyyyMMddHHmmss><序号>``，单次进程内保证不重复。
    """
    _SEQ["base"] = (_SEQ["base"] + 1) % (10 ** width)
    return f"{prefix}{now().strftime('%Y%m%d%H%M%S')}{_SEQ['base']:0{width}d}"


def now() -> datetime:
    """当前本地时间（东八区 naive datetime，便于直接落库）。"""
    return datetime.now(_CN_TZ).replace(tzinfo=None)


def today() -> date:
    return now().date()


def request_hash(payload: Any) -> str:
    """计算请求体指纹：同一幂等键 + 不同参数视为不同请求。"""
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def round2(value: float) -> float:
    """统一保留两位小数。"""
    return round(float(value) + 0.0, 2)


def safe_pct(numerator: float, denominator: float, digits: int = 2) -> float:
    """安全百分比：分母为 0 时返回 0，避免 ZeroDivisionError。"""
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator) * 100, digits)


def ctx_window(days: int) -> tuple[datetime, datetime]:
    """返回 [今天-days, 现在] 的时间窗口。"""
    end = now()
    return end - timedelta(days=days), end


def date_range_list(start: date, end: date) -> list[date]:
    """生成日期列表（含首尾），用于报表补零。"""
    result, cur = [], start
    while cur <= end:
        result.append(cur)
        cur += timedelta(days=1)
    return result
