"""pytest 全局夹具。

要点：

* 通过环境变量把数据库切到**临时目录的 SQLite**，与本地开发库完全隔离；
* 每个用例都重建全部 31 张表并重新播种主数据，保证用例之间零耦合；
* 关闭数采网关定时任务，避免后台协程干扰断言。
"""

from __future__ import annotations

import os
import tempfile
from typing import Iterator

import pytest

_TMP_DIR = tempfile.mkdtemp(prefix="mes-pytest-")
os.environ["DB_ENGINE"] = "sqlite"
os.environ["SQLITE_PATH"] = os.path.join(_TMP_DIR, "pytest.db")
os.environ["GATEWAY_ENABLED"] = "false"
os.environ["APP_ENV"] = "test"
os.environ["SQL_ECHO"] = "false"

from sqlalchemy.orm import Session  # noqa: E402

from scripts.seed import PRODUCTS, seed_master_data  # noqa: E402


@pytest.fixture()
def db() -> Iterator[Session]:
    """每个用例一套全新的数据库 + 主数据。"""
    from app.db.session import Base, SessionLocal, engine
    from app.services.auth_service import AuthService

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    seed_master_data(session)
    AuthService(session).ensure_default_rbac()
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def first_product(db: Session):
    from app.models.master import MdProduct

    return db.query(MdProduct).filter(MdProduct.code == PRODUCTS[0]["code"]).first()


@pytest.fixture()
def first_routing(db, first_product):
    from app.models.master import MdRouting

    return db.query(MdRouting).filter(MdRouting.product_id == first_product.id).first()


@pytest.fixture()
def operators(db):
    from app.models.master import MdEmployee

    return db.query(MdEmployee).all()


@pytest.fixture()
def shifts(db):
    from app.models.master import MdShift

    return db.query(MdShift).all()


@pytest.fixture()
def spc_operation_source(db, first_routing):
    """取工艺路线中启用了 SPC 的工序模板。"""
    from app.models.master import MdRoutingOperation

    return (
        db.query(MdRoutingOperation)
        .filter(MdRoutingOperation.routing_id == first_routing.id,
                MdRoutingOperation.spc_enabled.is_(True))
        .first()
    )


@pytest.fixture()
def new_order(db, first_product, first_routing):
    """创建一张草稿工单。"""
    from app.services.order_service import OrderService

    return OrderService(db).create_order(
        product_id=first_product.id,
        routing_id=first_routing.id,
        qty_planned=100,
        priority=3,
        operator="pytest",
    )


@pytest.fixture()
def committed_order(db, new_order):
    """已提交的草稿工单（提交后用例自身回滚不会误删夹具数据）。"""
    db.commit()
    return new_order


@pytest.fixture()
def running_order(db, new_order):
    """把工单推进到 IN_PROGRESS 并提交，返回 (工单, 首道工序)。"""
    from app.models.order import PpWorkOrderOperation
    from app.services.order_service import OrderService

    service = OrderService(db)
    service.transition(new_order.id, "RELEASED", "pytest")
    service.transition(new_order.id, "IN_PROGRESS", "pytest")
    operation = (
        db.query(PpWorkOrderOperation)
        .filter(PpWorkOrderOperation.work_order_id == new_order.id)
        .order_by(PpWorkOrderOperation.seq.asc())
        .first()
    )
    db.commit()
    return new_order, operation


@pytest.fixture()
def api_client(db):
    """返回绑定当前数据库的 TestClient 与三个角色的令牌。"""
    from fastapi.testclient import TestClient

    from app.core.security import create_access_token
    from app.main import app
    from app.models.rbac import SysUser
    from app.services.auth_service import AuthService

    client = TestClient(app)

    def token_for(username: str) -> str:
        user = db.query(SysUser).filter(SysUser.username == username).first()
        return create_access_token(user.username, extra={"uid": user.id})

    with client:
        yield client, token_for("admin"), token_for("leader"), token_for("worker")

    _ = AuthService  # 保持导入语义清晰
