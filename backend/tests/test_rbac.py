"""RBAC 权限测试：登录、三类角色、接口级鉴权。"""

from __future__ import annotations

import pytest

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import create_access_token, decode_access_token, hash_password, \
    verify_password
from app.core.permission_catalog import DEMO_PASSWORD, ROLE_PERMISSIONS
from app.models.rbac import SysUser
from app.services.auth_service import AuthService


# ------------------------------------------------------------------ 口令散列
def test_password_hash_and_verify():
    hashed = hash_password("mes@2026")
    assert hashed != "mes@2026"
    assert verify_password("mes@2026", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_hash_salt_is_random():
    assert hash_password("same") != hash_password("same")


# ------------------------------------------------------------------ 令牌
def test_login_returns_valid_token(db):
    token = AuthService(db).authenticate("admin", DEMO_PASSWORD)
    payload = decode_access_token(token)
    assert payload["sub"] == "admin"
    assert payload["uid"] > 0
    db.commit()


def test_login_rejects_wrong_password(db):
    with pytest.raises(UnauthorizedError):
        AuthService(db).authenticate("admin", "bad-password")


def test_expired_or_forged_token_is_rejected(db):
    from datetime import timedelta

    token = create_access_token("admin", expires_delta=timedelta(seconds=-10))
    with pytest.raises(ValueError):
        decode_access_token(token)


def test_disabled_user_cannot_login(db):
    from app.models.rbac import SysUser

    svc = AuthService(db)
    user = db.query(SysUser).filter(SysUser.username == "leader").first()
    user.status = 0
    db.commit()
    with pytest.raises(UnauthorizedError):
        svc.authenticate("leader", DEMO_PASSWORD)


# ------------------------------------------------------------------ 权限矩阵
def test_three_roles_have_dedicated_permissions():
    assert set(ROLE_PERMISSIONS) == {"admin", "line_leader", "operator"}
    assert "order:report" in ROLE_PERMISSIONS["operator"]
    assert "order:cancel" not in ROLE_PERMISSIONS["operator"]
    assert "quality:handle" in ROLE_PERMISSIONS["line_leader"]
    assert "system:admin" in ROLE_PERMISSIONS["admin"]


def test_role_permission_mapping(db):
    svc = AuthService(db)
    admin = db.query(SysUser).filter(SysUser.username == "admin").first()
    worker = db.query(SysUser).filter(SysUser.username == "worker").first()
    leader = db.query(SysUser).filter(SysUser.username == "leader").first()

    assert set(svc.role_codes(admin.id)) == {"admin"}
    assert set(svc.role_codes(worker.id)) == {"operator"}
    assert set(svc.role_codes(leader.id)) == {"line_leader"}

    admin_codes = set(svc.permission_codes(admin.id))
    worker_codes = set(svc.permission_codes(worker.id))
    leader_codes = set(svc.permission_codes(leader.id))

    assert worker_codes < leader_codes < admin_codes
    assert "order:cancel" not in worker_codes
    assert "quality:handle" in leader_codes
    assert "system:admin" in admin_codes


def test_permission_revocation_takes_effect_immediately(db):
    """移除角色权限后，下一次鉴权立即失效（回源校验，不信任 token 快照）。"""
    from app.core.rbac import PermissionChecker
    from app.models.rbac import SysPermission, SysRole, SysRolePermission, SysUser

    leader = db.query(SysUser).filter(SysUser.username == "leader").first()
    role = db.query(SysRole).filter(SysRole.code == "line_leader").first()
    perm = db.query(SysPermission).filter(SysPermission.code == "quality:handle").first()
    link = db.query(SysRolePermission).filter(
        SysRolePermission.role_id == role.id,
        SysRolePermission.permission_id == perm.id).first()
    db.delete(link)
    db.commit()

    checker = PermissionChecker(["quality:handle"])
    token = create_access_token(leader.username, extra={"uid": leader.id})

    class _Cred:
        credentials = token

    with pytest.raises(ForbiddenError):
        checker(_Cred(), db)
