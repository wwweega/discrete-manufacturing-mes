"""认证与授权服务。

* 登录：校验账号口令 → 签发 JWT（payload 携带 uid/username/roles）；
* 当前用户：解析 Token 后**回源数据库**复核角色与启用状态，
  避免角色被回收后旧 Token 继续生效；
* 初始化：幂等写入 default 的角色 / 权限 / 演示账号。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import UnauthorizedError
from app.core.permission_catalog import (
    DEMO_PASSWORD,
    DEMO_USERS,
    PERMISSIONS,
    ROLE_PERMISSIONS,
    ROLES,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.models.rbac import (
    SysPermission,
    SysRole,
    SysRolePermission,
    SysUser,
    SysUserRole,
)


class AuthService:
    """用户认证与 RBAC 初始化。"""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ 登录
    def authenticate(self, username: str, password: str) -> str:
        """校验账号口令并返回 JWT。"""
        user = self.db.execute(
            select(SysUser).where(SysUser.username == username)
        ).scalars().first()
        if user is None or not verify_password(password, user.password_hash):
            raise UnauthorizedError("账号或密码错误")
        if int(user.status or 0) != 1:
            raise UnauthorizedError("该账号已停用，请联系管理员")

        roles = self.role_codes(user.id)
        user.last_login_at = datetime.now()
        self.db.flush()
        return create_access_token(
            user.username,
            extra={"uid": user.id, "real_name": user.real_name, "roles": sorted(roles)},
        )

    def current_user(self, username: str) -> SysUser:
        """按用户名加载当前登录用户。"""
        user = self.db.execute(
            select(SysUser).where(SysUser.username == username)
        ).scalars().first()
        if user is None or int(user.status or 0) != 1:
            raise UnauthorizedError("用户不存在或已停用")
        return user

    # ------------------------------------------------------------------ 权限
    def role_codes(self, user_id: int) -> set[str]:
        return set(
            self.db.execute(
                select(SysRole.code)
                .select_from(SysUserRole)
                .join(SysRole, SysRole.id == SysUserRole.role_id)
                .where(SysUserRole.user_id == user_id)
            ).scalars().all()
        )

    def permission_codes(self, user_id: int) -> list[str]:
        return list(
            self.db.execute(
                select(SysPermission.code)
                .select_from(SysUserRole)
                .join(SysRolePermission, SysRolePermission.role_id == SysUserRole.role_id)
                .join(SysPermission, SysPermission.id == SysRolePermission.permission_id)
                .where(SysUserRole.user_id == user_id)
                .order_by(SysPermission.code.asc())
            ).scalars().all()
        )

    # ------------------------------------------------------------------ 初始化
    def ensure_default_rbac(self) -> dict:
        """幂等初始化 RBAC 数据，返回统计信息。"""
        stats = {"roles": 0, "permissions": 0, "users": 0, "grants": 0}

        perm_map: dict[str, SysPermission] = {}
        for code, name, module, is_write in PERMISSIONS:
            perm = self.db.execute(
                select(SysPermission).where(SysPermission.code == code)
            ).scalars().first()
            if perm is None:
                perm = SysPermission(code=code, name=name, module=module,
                                     is_write=is_write)
                self.db.add(perm)
                stats["permissions"] += 1
            perm_map[code] = perm
        self.db.flush()

        role_map: dict[str, SysRole] = {}
        for code, name, desc in ROLES:
            role = self.db.execute(
                select(SysRole).where(SysRole.code == code)
            ).scalars().first()
            if role is None:
                role = SysRole(code=code, name=name, description=desc)
                self.db.add(role)
                stats["roles"] += 1
            role_map[code] = role
        self.db.flush()

        for role_code, codes in ROLE_PERMISSIONS.items():
            role = role_map[role_code]
            for code in codes:
                perm = perm_map[code]
                exist = self.db.execute(
                    select(SysRolePermission).where(
                        SysRolePermission.role_id == role.id,
                        SysRolePermission.permission_id == perm.id,
                    )
                ).scalars().first()
                if exist is None:
                    self.db.add(SysRolePermission(role_id=role.id,
                                                  permission_id=perm.id))
                    stats["grants"] += 1
        self.db.flush()

        for username, real_name, emp_no, email, role_code in DEMO_USERS:
            user = self.db.execute(
                select(SysUser).where(SysUser.username == username)
            ).scalars().first()
            if user is None:
                user = SysUser(
                    username=username,
                    password_hash=hash_password(DEMO_PASSWORD),
                    real_name=real_name,
                    employee_no=emp_no,
                    email=email,
                    status=1,
                )
                self.db.add(user)
                self.db.flush()
                stats["users"] += 1
            link = self.db.execute(
                select(SysUserRole).where(
                    SysUserRole.user_id == user.id,
                    SysUserRole.role_id == role_map[role_code].id,
                )
            ).scalars().first()
            if link is None:
                self.db.add(SysUserRole(user_id=user.id,
                                        role_id=role_map[role_code].id))
        self.db.flush()
        return stats
