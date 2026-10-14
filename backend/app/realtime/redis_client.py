"""Redis 缓存客户端（带内存降级）。

用途：缓存设备实时状态与看板快照，让看板接口不落 DB 全表扫描。

降级策略
--------
本地演示形态（无 Redis 服务）时自动切换到内置的内存实现，
**接口语义与 Redis 完全一致**，因此上层代码无需区分部署形态。
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.core.config import settings

_DEVICE_KEY = "mes:device:status"
_DEVICE_CHANNEL = "mes:channel:device"
_DASHBOARD_KEY = "mes:dashboard:snapshot"


class _MemoryBackend:
    """进程内 KV + 过期 + 发布订阅，用于无 Redis 时的降级。"""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}
        self._subscribers: list[Any] = []
        self._lock = threading.Lock()

    def setex(self, key: str, ttl: int, value: str) -> None:
        with self._lock:
            self._store[key] = (value, time.time() + ttl)

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._store.get(key)
        if item is None:
            return None
        value, expire_at = item
        if expire_at < time.time():
            with self._lock:
                self._store.pop(key, None)
            return None
        return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def publish(self, channel: str, message: str) -> None:
        for callback in list(self._subscribers):
            callback(channel, message)

    def add_subscriber(self, callback: Any) -> None:
        self._subscribers.append(callback)


class RedisCache:
    """统一缓存接口，优先 Redis，失败自动降级为内存实现。"""

    def __init__(self) -> None:
        self._redis = None
        self._memory = _MemoryBackend()
        self._using_redis = False
        self._connect()

    # ------------------------------------------------------------ 连接
    def _connect(self) -> None:
        # 显式关闭或未配置主机时，直接进入内存降级，不再尝试建连
        if not settings.REDIS_ENABLED or not (settings.REDIS_HOST or "").strip():
            return
        try:  # pragma: no cover - 依赖外部服务
            import redis  # type: ignore

            client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            client.ping()
            self._redis = client
            self._using_redis = True
        except Exception:
            self._redis = None
            self._using_redis = False

    @property
    def backend_name(self) -> str:
        return "redis" if self._using_redis else "memory"

    @property
    def is_redis(self) -> bool:
        return self._using_redis

    # ------------------------------------------------------------ 基础操作
    def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        if self._redis is not None:
            self._redis.setex(key, ttl or settings.DEVICE_STATUS_TTL_SEC, raw)
        else:
            self._memory.setex(key, ttl or settings.DEVICE_STATUS_TTL_SEC, raw)

    def get_json(self, key: str, default: Any = None) -> Any:
        raw = self._get(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    def _get(self, key: str) -> str | None:
        try:
            if self._redis is not None:
                return self._redis.get(key)
        except Exception:
            self._redis = None
            self._using_redis = False
        return self._memory.get(key)

    def delete(self, key: str) -> None:
        try:
            if self._redis is not None:
                self._redis.delete(key)
                return
        except Exception:
            self._redis = None
            self._using_redis = False
        self._memory.delete(key)

    def ping(self) -> tuple[bool, str]:
        """健康检查：[是否可用, 后端名称]。

        内存降级同样是可用的缓存后端，因此返回 ``(True, "memory")``；
        调用方可通过第二个返回值区分当前使用的是 Redis 还是内存实现。
        """
        try:
            if self._redis is not None:
                self._redis.ping()
                return True, "redis"
        except Exception:
            self._redis = None
            self._using_redis = False
        return True, "memory"

    # ------------------------------------------------------------ 设备状态
    def write_device_status(self, equipment_code: str, payload: dict) -> None:
        """写入单台设备的实时状态（Hash 结构，便于单字段读取）。"""
        key = f"{_DEVICE_KEY}:{equipment_code}"
        self.set_json(key, payload, ttl=settings.DEVICE_STATUS_TTL_SEC)

    def read_device_status(self, equipment_code: str) -> dict | None:
        return self.get_json(f"{_DEVICE_KEY}:{equipment_code}")

    def write_device_snapshot(self, devices: list[dict]) -> None:
        """整批写入设备快照 + 看板快照，SSE 轮询直接从这里读。"""
        for device in devices:
            self.write_device_status(device["equipment_code"], device)
        self.set_json(_DASHBOARD_KEY, {
            "devices": devices,
            "updated_at": time.time(),
        }, ttl=settings.DEVICE_STATUS_TTL_SEC)

    def read_dashboard_snapshot(self) -> dict:
        return self.get_json(_DASHBOARD_KEY, {"devices": [], "updated_at": 0}) or {
            "devices": [], "updated_at": 0
        }

    def publish_device_event(self, payload: dict) -> None:
        """发布设备事件，供 SSE 推送到前端。"""
        raw = json.dumps(payload, ensure_ascii=False, default=str)
        try:
            if self._redis is not None:
                self._redis.publish(_DEVICE_CHANNEL, raw)
                return
        except Exception:
            self._redis = None
            self._using_redis = False
        self._memory.publish(_DEVICE_CHANNEL, raw)

    def subscribe_device_events(self, callback: Any) -> None:
        """注册设备事件订阅回调（降级时走内存 pub/sub）。"""
        if self._redis is not None:
            self._start_redis_listener(callback)
        else:
            self._memory.add_subscriber(callback)

    def _start_redis_listener(self, callback: Any) -> None:  # pragma: no cover
        """后台线程监听 Redis 频道，把消息转给 asyncio 回调。"""

        def _run() -> None:
            try:
                pubsub = self._redis.pubsub()
                pubsub.subscribe(_DEVICE_CHANNEL)
                for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    callback(_DEVICE_CHANNEL, message.get("data"))
            except Exception:
                self._redis = None
                self._using_redis = False

        thread = threading.Thread(target=_run, daemon=True, name="redis-listener")
        thread.start()


_cache: RedisCache | None = None


def get_cache() -> RedisCache:
    """单例缓存客户端。"""
    global _cache
    if _cache is None:
        _cache = RedisCache()
    return _cache
