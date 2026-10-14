"""设备数采网关 + Redis/SSE 实时链路测试。"""

from __future__ import annotations

import pytest

from app.models.equipment import EqStatusLog
from app.realtime.device_gateway import DeviceGateway
from app.realtime.redis_client import RedisCache, get_cache
from app.realtime.sse_hub import SSEHub


def test_gateway_collects_frame_for_every_equipment(db):
    from app.models.master import MdEquipment

    gateway = DeviceGateway(write_db=True, seed=7)
    frame = gateway.tick()
    expect = db.query(MdEquipment).count()

    assert len(frame["devices"]) == expect
    assert frame["summary"]["total"] == expect
    assert 0 <= frame["summary"]["utilization"] <= 100


def test_gateway_persists_status_logs(db):
    from app.models.master import MdEquipment

    before = db.query(EqStatusLog).count()
    DeviceGateway(write_db=True, seed=11).tick()
    db.commit()

    equipment_count = db.query(MdEquipment).count()
    assert db.query(EqStatusLog).count() >= before + equipment_count


def test_gateway_writes_cache_snapshot(db):
    cache = get_cache()
    DeviceGateway(write_db=True, seed=13).tick()
    snapshot = cache.read_dashboard_snapshot()
    assert snapshot["devices"], "设备快照必须写入缓存供看板读取"
    assert isinstance(snapshot["devices"][0]["equipment_code"], str)


def test_realtime_device_status_readable_by_code(db):
    from app.models.master import MdEquipment

    gateway = DeviceGateway(write_db=True, seed=17)
    gateway.tick()
    equipment = db.query(MdEquipment).first()
    status = get_cache().read_device_status(equipment.code)
    assert status is not None
    assert status["equipment_code"] == equipment.code


def test_running_equipment_produces_output(db, running_order):
    """存在加工中工序时，对应设备应在缓存中有实时状态。"""
    from app.models.master import MdEquipment

    order, operation = running_order
    equipment_id = operation.equipment_id
    if equipment_id is None:
        first = db.query(MdEquipment).first()
        operation.equipment_id = first.id
        db.commit()
        equipment_id = first.id

    DeviceGateway(write_db=True, seed=23).tick()
    equipment = db.get(MdEquipment, equipment_id)
    status = get_cache().read_device_status(equipment.code)
    assert status is not None
    assert status["status"] in {"RUN", "IDLE", "FAULT"}


def test_sse_hub_broadcasts_to_subscriber(db):
    import asyncio

    async def _run(hub: SSEHub):
        queue = await hub.subscribe()
        hub.publish("dashboard", {"k": "v"})
        frame = await asyncio.wait_for(queue.get(), timeout=1)
        return frame

    hub = SSEHub()
    frame = asyncio.run(_run(hub))
    assert frame["event"] == "dashboard"
    assert frame["data"] == {"k": "v"}


def test_sse_hub_drops_old_frames_on_slow_consumer():
    import asyncio

    async def _run(hub: SSEHub):
        queue = await hub.subscribe()
        for i in range(10):
            hub.publish("dashboard", {"i": i})
        # 队列上界为 3，慢消费者只会保留最新帧，不应该阻塞
        await asyncio.sleep(0)
        return queue.qsize()

    assert asyncio.run(_run(SSEHub())) <= 3


def test_cache_backend_reports_name():
    """两种后端都可以对外声明"可用"，靠 backend 名称区分实现。"""
    cache = get_cache()
    assert cache.backend_name in {"redis", "memory"}
    healthy, backend = cache.ping()
    assert backend == cache.backend_name
    assert healthy is True


def test_cache_falls_back_to_memory_when_redis_disabled(monkeypatch):
    """REDIS_ENABLED=false / 主机留空时直接走内存实现，不再尝试建连。"""
    monkeypatch.setenv("REDIS_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        cache = RedisCache()
        assert cache.backend_name == "memory"
        assert cache.is_redis is False
        cache.write_device_status("EQ-TEST", {"status": "RUNNING"})
        assert cache.read_device_status("EQ-TEST")["status"] == "RUNNING"
    finally:
        monkeypatch.delenv("REDIS_ENABLED", raising=False)
        get_settings.cache_clear()
