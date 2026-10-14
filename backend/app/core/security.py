"""口令散列与 JWT 令牌签发。

口令散列使用标准库 PBKDF2-HMAC-SHA256（迭代次数可配置），
避免引入需要编译的第三方依赖（bcrypt/argon2），保证在纯 Python 环境下
也能一键安装、一键运行；同时保留加盐 + 定长比较，符合安全基线要求。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import PyJWTError

from app.core.config import settings


# ---------------------------------------------------------------- 口令散列
def hash_password(plain: str) -> str:
    """生成 `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>` 形式的密文。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt,
        settings.PASSWORD_ITERATIONS,
    )
    return "{}:{}:{}:{}".format(
        settings.PASSWORD_SCHEME,
        settings.PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文口令，常量时间比较。"""
    try:
        scheme, iterations, salt_b64, hash_b64 = hashed.split(":")
        if scheme != settings.PASSWORD_SCHEME:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            plain.encode("utf-8"),
            base64.b64decode(salt_b64),
            int(iterations),
        )
        return hmac.compare_digest(base64.b64decode(hash_b64), dk)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- JWT
def create_access_token(subject: str, extra: dict[str, Any] | None = None,
                        expires_delta: timedelta | None = None) -> str:
    """签发访问令牌，payload 内含用户名与角色码，供 RBAC 鉴权使用。"""
    expire = datetime.now(tz=timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {"sub": subject, "exp": expire, "iat": datetime.now(tz=timezone.utc)}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """解析令牌，任何异常统一转换为 None 以外的可读错误由调用方处理。"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except PyJWTError as exc:  # 过期 / 签名不符 / 结构非法
        raise ValueError(f"令牌无效或已过期：{exc}") from exc
