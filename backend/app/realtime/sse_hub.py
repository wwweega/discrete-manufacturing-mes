"""SSE 推送中心。

浏览器通过 ``EventSource`` 长连接订阅，后端每 ``SSE_PUSH_INTERVAL_SEC`` 秒
推送一帧看板快照，形成「车间看板秒级刷新」的效果。

实现要点：

* 每个订阅者一个 ``asyncio.Queue``，慢消费者丢弃旧帧（只保最新），避免内存膨胀；
* 设备数采网关写入 Redis 后调用 :meth:`SSEHub.publish`，由这里广播到全部连接；
* 即使没有任何 Redis 也能工作 —— 网关会使用同一进程的内存后端。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.core.config import settings

_MAX_QUEUE = 3


class SSEHub:
    """极简 SSE 广播中心（单进程足以支撑车间级并发）。"""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._latest: dict[str, Any] | None = None
        self._last_push_at: float = 0.0

    # ------------------------------------------------------------ 订阅管理
    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._subscribers.add(queue)
        if self._latest:
            self._offer(queue, self._latest)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # ------------------------------------------------------------ 广播
    def publish(self, event: str, data: dict) -> None:
        """广播一帧数据（同步 API，供网关线程/任务调用）。"""
        frame = {"event": event, "data": data, "ts": int(time.time())}
        self._latest = frame
        for queue in list(self._subscribers):
            self._offer(queue, frame)

    @staticmethod
    def _offer(queue: asyncio.Queue, frame: dict) -> None:
        """投递一帧；队列满时丢弃最旧的一帧，保证推送的实时性而非堆积。"""
        try:
            queue.put_nowait(frame)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                pass

    async def stream(self, queue: asyncio.Queue, *, keepalive_sec: int | None = None):
        """产出符合 SSE 协议规范的文本流。"""
        keepalive = keepalive_sec or settings.SSE_HEARTBEAT_SEC
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=keepalive)
                    yield (
                        f"event: {frame['event']}\n"
                        f"data: {json.dumps(frame['data'], ensure_ascii=False, default=str)}\n\n"
                    )
                except asyncio.TimeoutError:
                    # 心跳注释帧，防止反向代理因空闲断开连接
                    yield f": keepalive {int(time.time())}\n\n"
        finally:
            self.unsubscribe(queue)


hub = SSEHub()
