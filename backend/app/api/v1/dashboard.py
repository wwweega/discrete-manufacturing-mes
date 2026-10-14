"""车间看板与设备实时数据接口（含 SSE 推送）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.core.rbac import require_permissions
from app.core.response import ApiResponse, ok
from app.models.equipment import EqStatusLog
from app.models.master import MdEquipment
from app.realtime import get_gateway, hub
from app.realtime.redis_client import get_cache
from app.services.dashboard_service import DashboardService, EquipmentService

router = APIRouter(prefix="/dashboard", tags=["车间看板"])

_VIEW = require_permissions("dashboard:view")


@router.get(
    "",
    response_model=ApiResponse[dict],
    summary="看板总览（一次请求返回整屏数据）",
    dependencies=[Depends(_VIEW)],
)
def overview(db: Session = Depends(get_db)) -> dict:
    return ok(DashboardService(db).overview())


@router.get(
    "/status-distribution",
    response_model=ApiResponse[list],
    summary="工单状态分布（饼图数据）",
    dependencies=[Depends(_VIEW)],
)
def status_distribution(db: Session = Depends(get_db)) -> dict:
    return ok(DashboardService(db).status_distribution())


@router.get(
    "/recent-reports",
    response_model=ApiResponse[list],
    summary="最近报工流水",
    dependencies=[Depends(_VIEW)],
)
def recent_reports(limit: int = Query(8, ge=1, le=50),
                   db: Session = Depends(get_db)) -> dict:
    return ok(DashboardService(db).recent_reports(limit))


@router.get(
    "/output-trend",
    response_model=ApiResponse[dict],
    summary="近 N 天产量趋势（折线图数据）",
    dependencies=[Depends(_VIEW)],
)
def output_trend(days: int = Query(7, ge=1, le=60),
                 db: Session = Depends(get_db)) -> dict:
    return ok(DashboardService(db).orders.progress_matrix() | {
        "series": ReportTrendMixin(db).daily_output(days)
    })


@router.get(
    "/realtime",
    response_model=ApiResponse[dict],
    summary="设备实时状态快照",
    description="直接从 Redis（无处组件时为内存实现）读取，不落 DB 查询。",
    dependencies=[Depends(require_permissions("equipment:view"))],
)
def realtime_snapshot(db: Session = Depends(get_db)) -> dict:
    return ok(EquipmentService(db).running_realtime())


@router.post(
    "/gateway/collect",
    response_model=ApiResponse[dict],
    summary="手动触发一次设备数据采集",
    description="用于演示与调试：不等定时任务，立即让数采网关采集并推送一帧。",
    dependencies=[Depends(require_permissions("equipment:view"))],
)
def collect_once(db: Session = Depends(get_db)) -> dict:
    gateway = get_gateway()
    frame = gateway.tick()
    return ok({
        "summary": frame["summary"],
        "alarms": frame["alarms"],
        "device_count": len(frame["devices"]),
    })


@router.get(
    "/gateway/status",
    response_model=ApiResponse[dict],
    summary="数采网关与缓存健康状态",
)
def gateway_status() -> dict:
    cache = get_cache()
    healthy, backend = cache.ping()
    return ok({
        "gateway_enabled": settings.GATEWAY_ENABLED,
        "gateway_interval_sec": settings.GATEWAY_INTERVAL_SEC,
        "cache_backend": backend,
        "cache_healthy": healthy,
        "sse_subscribers": hub.subscriber_count,
    })


@router.get(
    "/stream",
    summary="SSE 实时推送",
    description=(
        "以 text/event-stream 长连接推送车间看板数据，每 "
        f"{settings.SSE_PUSH_INTERVAL_SEC} 秒一帧，实现看板秒级刷新。\n\n"
        "浏览器用法：`new EventSource('/api/v1/dashboard/stream?token=<JWT>')`"
    ),
)
async def stream(token: str = Query("", description="JWT 访问令牌")) -> StreamingResponse:
    """推送 SSE 数据流。

    ``EventSource`` 规范不支持自定义请求头，因此令牌通过 query 参数传递；
    仍会做与其余接口一致的 RBAC 校验（dashboard:view）。
    """
    from sqlalchemy.orm import Session

    from app.core.exceptions import ForbiddenError, UnauthorizedError
    from app.core.security import decode_access_token
    from app.db.session import SessionLocal
    from app.services.auth_service import AuthService

    if not token:
        raise UnauthorizedError("缺少访问令牌，请通过 ?token=<JWT> 传入")

    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise UnauthorizedError(str(exc))

    db: Session = SessionLocal()
    try:
        user = AuthService(db).current_user(str(payload.get("sub") or ""))
        codes = set(AuthService(db).permission_codes(int(user.id)))
        if not codes.intersection({"dashboard:view"}):
            raise ForbiddenError("无查看车间看板的权限")
    finally:
        db.close()

    queue = await hub.subscribe()
    return StreamingResponse(
        hub.stream(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class ReportTrendMixin:
    """产出趋势查询的内联工具（避免在 services 里再加一层）。"""

    def __init__(self, db: Session):
        self.db = db

    def daily_output(self, days: int) -> list[dict]:
        from app.models.order import PpWorkReport

        since = datetime.now() - timedelta(days=days)
        rows = self.db.execute(
            select(
                func.date(PpWorkReport.report_time).label("day"),
                func.sum(PpWorkReport.qty_good),
                func.sum(PpWorkReport.qty_defect),
            )
            .where(PpWorkReport.report_time >= since)
            .group_by(func.date(PpWorkReport.report_time))
        ).all()
        return [{
            "day": str(row[0]),
            "qty_good": int(row[1] or 0),
            "qty_defect": int(row[2] or 0),
        } for row in rows]


@router.get(
    "/equipment-summary",
    response_model=ApiResponse[dict],
    summary="设备状态汇总与稼动率",
    dependencies=[Depends(require_permissions("equipment:view"))],
)
def equipment_summary(
    since_hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now() - timedelta(hours=since_hours)
    service = EquipmentService(db)
    return ok({
        "devices": service.list_equipment(),
        "utilization": service.utilization(since=since),
        "alarm_summary": service.alarm_summary(),
        "log_count": int(db.execute(
            select(func.count(EqStatusLog.id)).where(
                EqStatusLog.collected_at >= since
            )
        ).scalar_one()),
        "equipment_count": int(db.execute(
            select(func.count(MdEquipment.id))
        ).scalar_one()),
    })
