"""API 层公共依赖。

* :func:`get_db` —— 请求级会话；
* :func:`get_current_user` —— 解析 Bearer Token 并回源校验用户状态；
* :func:`get_operator` —— 返回操作人账号，写操作统一用它做追溯。
"""

from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.rbac import SysUser
from app.services.auth_service import AuthService

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> SysUser:
    """从 Token 加载当前用户（每次回源校验启用状态）。"""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("未提供访问令牌，请先登录")
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise UnauthorizedError(str(exc))
    username = payload.get("sub")
    if not username:
        raise UnauthorizedError("令牌缺少用户标识")
    return AuthService(db).current_user(username)


def get_operator(user: SysUser = Depends(get_current_user)) -> str:
    """返回操作人账号，用于业务留痕与幂等记录。"""
    return user.username


def get_user_id(user: SysUser = Depends(get_current_user)) -> int:
    """返回当前用户主键。"""
    return int(user.id)
