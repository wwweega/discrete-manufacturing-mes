"""应用配置中心。

所有配置项均可通过环境变量覆盖，也可通过仓库根目录的 .env 文件覆盖。
支持的部署形态：

* Docker Compose：DB_ENGINE=mysql，连接 compose 内的 mysql / redis 服务；
* 本地直跑：DB_ENGINE=sqlite（默认），无需安装 MySQL / Redis 即可完成演示，
  但 Redis 相关的实时推送能力会自动退化为进程内内存实现（见 app/realtime/redis_client.py）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """全局配置对象。"""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------- 应用 ----------------
    APP_NAME: str = "离散制造车间生产管理系统"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "dev"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    # ---------------- 数据库 ----------------
    DB_ENGINE: str = "sqlite"          # sqlite | mysql
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "mes123456"
    MYSQL_DB: str = "mes"
    SQLITE_PATH: str = str(ROOT_DIR / "data" / "mes.db")
    SQL_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # ---------------- Redis ----------------
    # REDIS_ENABLED=false 或 REDIS_HOST 留空时，直接使用进程内内存缓存（见 redis_client.py）
    REDIS_ENABLED: bool = True
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    DEVICE_STATUS_TTL_SEC: int = 600
    IDEMPOTENCY_TTL_SEC: int = 86400

    # ---------------- 安全 ----------------
    SECRET_KEY: str = "mes-discrete-workshop-secret-key-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    PASSWORD_SCHEME: str = "pbkdf2_sha256"
    PASSWORD_ITERATIONS: int = 120_000

    # ---------------- 设备数采网关 ----------------
    GATEWAY_ENABLED: bool = True
    GATEWAY_INTERVAL_SEC: int = 3        # 网关上报周期（秒）
    SSE_HEARTBEAT_SEC: int = 15          # SSE 心跳
    SSE_PUSH_INTERVAL_SEC: int = 2       # 看板推送周期（秒）：秒级刷新
    DEVICE_OFFLINE_TIMEOUT_SEC: int = 30  # 超过该时长未上报判定为离线

    # ---------------- SPC ----------------
    SPC_DEFAULT_SUBGROUP_SIZE: int = 5   # 子组容量 n，X̄-R 图典型取值
    SPC_RULE_SET: str = "1,2,3,5,6"      # 启用的判异准则编号

    # ---------------- 前端静态资源 ----------------
    # dist      = Vite 构建产物（npm run build 后生成，生产推荐）
    # standalone = 免构建演示版（零 npm 依赖，仅依赖本地 vendor）
    FRONTEND_PREFER: str = "dist"

    # ---------------- 分页 ----------------
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 200

    @property
    def database_url(self) -> str:
        """按 DB_ENGINE 生成 SQLAlchemy URL。"""
        if self.DB_ENGINE == "mysql":
            return (
                f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
                f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
            )
        return f"sqlite:///{self.SQLITE_PATH}"

    @property
    def is_sqlite(self) -> bool:
        return self.DB_ENGINE == "sqlite"


@lru_cache
def get_settings() -> Settings:
    """单例访问配置。"""
    return Settings()


settings = get_settings()
