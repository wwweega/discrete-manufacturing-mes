"""实时模块：Redis 缓存、数采网关、SSE 推送。

对应简历：「模拟设备数采网关定时上报运行数据，Redis 缓存设备实时状态，
SSE 向前端推送，车间看板秒级刷新」。
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.realtime.device_gateway import DeviceGateway
from app.realtime.redis_client import RedisCache, get_cache
from app.realtime.sse_hub import SSEHub, hub

__all__ = ["DeviceGateway", "RedisCache", "SSEHub", "get_cache", "hub",
           "get_gateway", "start_realtime", "stop_realtime"]

_gateway: DeviceGateway | None = None


def get_gateway() -> DeviceGateway:
    """获取数采网关实例（按需延迟创建），并注册 SSE 转发。

    网关把每帧数据同时写 Redis 频道；这里再订阅一次并向 SSE Hub 广播，
    使得多进程 / 多副本部署时（Redis 版）前端仍能从任意副本收到推送。
    """
    global _gateway
    if _gateway is None:
        _gateway = DeviceGateway()
        cache = get_cache()

        def _forward(channel: str, message: str) -> None:
            """把 Redis 频道消息转交给 SSE Hub（幂等且无事件循环依赖）。"""
            import json

            try:
                payload = json.loads(message)
            except ValueError:
                return
            hub.publish(payload.get("event", "dashboard"), payload.get("data", {}))

        cache.subscribe_device_events(_forward)
    return _gateway


async def start_realtime(interval_sec: int | None = None) -> DeviceGateway:
    """启动数采网关（FastAPI lifespan 调用）。"""
    gateway = get_gateway()
    if interval_sec:
        gateway.interval = interval_sec
    if settings.GATEWAY_ENABLED:
        await gateway.start()
    return gateway


async def stop_realtime() -> None:
    """停止数采网关。"""
    if _gateway is not None:
        await _gateway.stop()
