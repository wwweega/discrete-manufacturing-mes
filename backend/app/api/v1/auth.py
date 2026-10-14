"""认证接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.response import ApiResponse, ok
from app.db.unit_of_work import transactional
from app.schemas.common import LoginRequest, TokenResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post(
    "/login",
    response_model=ApiResponse[TokenResponse],
    summary="用户登录",
    description=(
        "校验账号口令后签发 JWT。内置演示账号（密码均为 `mes@2026`）：\n\n"
        "- `admin` 管理员\n- `leader` 班组长\n- `worker` 操作工\n\n"
        "不同角色拥有的接口权限不同，可用 Swagger 右上角 Authorize 按钮切换体验 RBAC。"
    ),
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    service = AuthService(db)
    with transactional(db):
        token = service.authenticate(payload.username, payload.password)
        user = service.current_user(payload.username)
        data = TokenResponse(
            access_token=token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            username=user.username,
            real_name=user.real_name,
            roles=sorted(service.role_codes(user.id)),
            permissions=service.permission_codes(user.id),
        )
    return ok(data.model_dump())


@router.get(
    "/me",
    response_model=ApiResponse[dict],
    summary="获取当前登录用户及权限",
)
def me(current_user=Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service = AuthService(db)
    return ok({
        "id": current_user.id,
        "username": current_user.username,
        "real_name": current_user.real_name,
        "employee_no": current_user.employee_no,
        "roles": sorted(service.role_codes(current_user.id)),
        "permissions": service.permission_codes(current_user.id),
    })
