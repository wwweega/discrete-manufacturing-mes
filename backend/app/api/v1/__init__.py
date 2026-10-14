"""v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1 import auth, dashboard, inventory, master, orders, quality, reports
from app.core.config import settings

api_router = APIRouter(prefix=settings.API_PREFIX)
api_router.include_router(auth.router)
api_router.include_router(master.router)
api_router.include_router(orders.router)
api_router.include_router(quality.router)
api_router.include_router(inventory.router)
api_router.include_router(dashboard.router)
api_router.include_router(reports.router)

__all__ = ["api_router"]
