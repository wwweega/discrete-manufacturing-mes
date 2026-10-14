"""FastAPI 应用入口。

启动后::

    Swagger 文档：http://localhost:8000/docs
    ReDoc 文档： http://localhost:8000/redoc
    前端界面：   http://localhost:8000/
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import api_router
from app.core.config import ROOT_DIR, settings
from app.core.response import fail
from app.db.session import init_db
from app.realtime import start_realtime, stop_realtime

logging.basicConfig(level=logging.INFO if not settings.DEBUG else logging.DEBUG)
logger = logging.getLogger("mes")

DESCRIPTION = """
面向**离散制造**场景的车间生产管理系统，覆盖核心业务链路：

> 生产工单 → 工序报工 → 设备状态采集 → 质量检验（SPC）→ 库存联动

## 角色与权限

内置三类角色，权限粒度到**单个接口**（RBAC）：

| 角色 | 账号 | 口令 | 主要权限 |
| --- | --- | --- | --- |
| 管理员 | `admin` | `mes@2026` | 全部接口 |
| 班组长 | `leader` | `mes@2026` | 工单下达/完工、质检处理、报表查看 |
| 操作工 | `worker` | `mes@2026` | 仅报工与查看 |

调用写接口时，如需幂等保护请在请求头携带 `Idempotency-Key`。
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：建表 → 启动数采网关 → 退出时停止。"""
    init_db()
    logger.info("数据表自检完成（%s 环境）", settings.DB_ENGINE)
    await start_realtime()
    logger.info("设备数采网关已启动，上报周期 %ss", settings.GATEWAY_INTERVAL_SEC)
    yield
    await stop_realtime()
    logger.info("设备数采网关已停止")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ---------------- 中间件 ----------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------- 异常处理器 ----------------
    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError):
        """把 Pydantic 校验错误转成**可读的中文字段级错误信息**。"""
        errors = []
        for item in exc.errors():
            loc = ".".join(str(p) for p in item.get("loc", [])[1:]) or "请求体"
            errors.append({"field": loc, "message": item.get("msg", "参数不合法")})
        detail = "；".join(f"{e['field']}: {e['message']}" for e in errors)
        return JSONResponse(
            status_code=422,
            content=fail(f"参数校验失败 → {detail}", code=4220, data={"errors": errors}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_: Request, exc: StarletteHTTPException):
        detail = exc.detail
        # 业务异常已在 exceptions.py 中构造为统一响应体，直接透传
        if isinstance(detail, dict) and {"code", "msg"} <= set(detail):
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(str(detail) or "请求失败", code=exc.status_code),
        )

    @app.exception_handler(Exception)
    async def _server_handler(_: Request, exc: Exception):
        logger.exception("未捕获异常：%s", exc)
        return JSONResponse(status_code=500, content=fail(f"服务内部错误：{exc}", code=5000))

    # ---------------- 路由 ----------------
    app.include_router(api_router)

    @app.get("/api/health", tags=["系统"], summary="健康检查（无需鉴权）")
    def health() -> dict:
        from app.realtime.redis_client import get_cache

        cache = get_cache()
        healthy, backend = cache.ping()
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "app": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "env": settings.APP_ENV,
                "db_engine": settings.DB_ENGINE,
                "cache_backend": backend,
                "cache_healthy": healthy,
            },
        }

    # ---------------- 静态前端（免构建演示模式） ----------------
    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """挂载内置静态资源。

    * ``FRONTEND_PREFER=dist``      —— Vite 构建产物（生产推荐）；
    * ``FRONTEND_PREFER=standalone`` —— 免构建演示版，无需 npm install。

    首选产物不存在时自动回退到另一个，保证任何形态下都能打开界面。
    """
    candidates = {
        "dist": ROOT_DIR / "frontend" / "dist",
        "standalone": ROOT_DIR / "frontend" / "standalone",
    }
    ordered = ["dist", "standalone"]
    preferred = settings.FRONTEND_PREFER if settings.FRONTEND_PREFER in ordered else "dist"
    ordered.remove(preferred)
    ordered.insert(0, preferred)

    for key in ordered:
        directory = candidates[key]
        if (directory / "index.html").exists():
            app.mount("/", StaticFiles(directory=str(directory), html=True), name="frontend")
            logger.info("已挂载前端静态资源（%s）：%s", key, directory)
            return
    logger.info("未找到前端资源，仅提供 API 服务")


app = create_app()


def main() -> None:  # pragma: no cover
    """命令行入口：`python -m app.main`。"""
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000,
                reload=settings.DEBUG, log_level="info")


if __name__ == "__main__":  # pragma: no cover
    main()
