"""RBAC 接口级权限控制。

设计要点
--------
* 三张主表 + 两张关联表实现「用户 - 角色 - 权限」三级模型
  （对应简历中的 *管理员 / 班组长 / 操作工* 三类角色）；
* 权限粒度到 **单个接口**：每个写接口通过 Depends 声明所需权限码，
  由 :func:`require_permissions` 生成的依赖项在调用前完成校验；
* 登录成功后角色码写入 JWT payload，鉴权时优先走 Token 快照，
  并回源数据库复核，避免角色变更后旧 Token 仍然生效。
"""

from __future__ import annotations

from typing import Iterable, Sequence

from fastapi import Depends
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import Session, get_db
from app.models.rbac import SysPermission, SysRole, SysRolePermission, SysUserRole

# HTTP Bearer 认证 Scheme，auto_error=False 以便自定义错误文案
bearer_scheme = HTTPBearer(auto_error=False)


# ------------------------------------------------------------------ 数据查询
def get_user_permission_codes(db: Session, user_id: int) -> set[str]:
    """查询用户拥有的全部权限码（角色去重合并）。"""
    stmt = (
        select(SysPermission.code)
        .select_from(SysUserRole)
        .join(SysRolePermission, SysRolePermission.role_id == SysUserRole.role_id)
        .join(SysPermission, SysPermission.id == SysRolePermission.permission_id)
        .where(SysUserRole.user_id == user_id)
    )
    return set(db.execute(stmt).scalars().all())


def get_user_role_codes(db: Session, user_id: int) -> set[str]:
    """查询用户的角色码集合。"""
    stmt = (
        select(SysRole.code)
        .select_from(SysUserRole)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .where(SysUserRole.user_id == user_id)
    )
    return set(db.execute(stmt).scalars().all())


def user_has_permission(db: Session, user_id: int, codes: Sequence[str]) -> bool:
    """判断用户是否拥有给定权限码中的任意一个。"""
    owned = get_user_permission_codes(db, user_id)
    return bool(owned.intersection(codes))


# ------------------------------------------------------------------ 依赖
class PermissionChecker:
    """接口级权限依赖项工厂。

    用法::

        @router.post("/{order_id}/release", dependencies=[Depends(require_permissions("order:release"))])
    """

    def __init__(self, codes: Iterable[str], require_all: bool = False):
        self.codes = list(codes)
        self.require_all = require_all

    def __call__(self, credentials=Depends(bearer_scheme),
                 db: Session = Depends(get_db)) -> dict:
        """校验 token 与权限码，返回解码后的 token payload。"""
        if credentials is None or not credentials.credentials:
            raise UnauthorizedError("未提供访问令牌，请先登录")
        try:
            payload = decode_access_token(credentials.credentials)
        except ValueError as exc:
            raise UnauthorizedError(str(exc))
        user_id = payload.get("uid")
        if not user_id:
            raise UnauthorizedError("令牌缺少用户标识")

        owned = get_user_permission_codes(db, int(user_id))
        if self.require_all:
            passed = set(self.codes).issubset(owned)
        else:
            passed = bool(owned.intersection(self.codes))
        if not passed:
            raise ForbiddenError(f"无操作权限，需要权限：{'/'.join(self.codes)}")
        payload["_permission_codes"] = sorted(owned)
        return payload


def require_permissions(*codes: str, require_all: bool = False) -> PermissionChecker:
    """生成一个接口级权限依赖项（任一权限通过即可，或全部通过）。"""
    return PermissionChecker(codes, require_all=require_all)


def require_roles(*role_codes: str) -> PermissionChecker:
    """按角色粗粒度校验：将角色转换为同名权限码 `role:<code>`。"""
    return PermissionChecker([f"role:{code}" for code in role_codes])


# 便于文档/测试复用的常量
SUPER_ADMIN_FLAG = settings.APP_ENV == "dev"
