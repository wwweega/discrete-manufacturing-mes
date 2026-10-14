"""RBAC 权限模型（5 张表）。

sys_user / sys_role / sys_permission 三张主表，
sys_user_role / sys_role_permission 两张关联表，
实现「用户 - 角色 - 权限」三级授权，权限码粒度到单个接口。

三类内置角色对应简历描述：

* ``admin``       管理员 —— 全部接口权限；
* ``line_leader`` 班组长 —— 工单下达、报工审核、质检处理；
* ``operator``    操作工 —— 仅报工、查看自身工单。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, table_comment


class SysUser(Base, TimestampMixin):
    """系统用户。"""

    __tablename__ = "sys_user"
    __table_args__ = table_comment("系统用户表")

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False,
                                          comment="登录账号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="口令散列")
    real_name: Mapped[str] = mapped_column(String(64), default="", nullable=False, comment="姓名")
    employee_no: Mapped[str] = mapped_column(String(32), default="", nullable=False,
                                             comment="关联员工工号")
    email: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="1启用 0停用")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True,
                                                           comment="最近登录时间")

    roles: Mapped[list["SysRole"]] = relationship(
        secondary="sys_user_role", back_populates="users", lazy="selectin"
    )


class SysRole(Base, TimestampMixin):
    """角色。"""

    __tablename__ = "sys_role"
    __table_args__ = table_comment("角色表")

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="角色码")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="角色名称")
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    users: Mapped[list[SysUser]] = relationship(
        secondary="sys_user_role", back_populates="roles", lazy="noload"
    )
    permissions: Mapped[list["SysPermission"]] = relationship(
        secondary="sys_role_permission", lazy="selectin"
    )


class SysPermission(Base, TimestampMixin):
    """接口权限点，code 与路由依赖中的权限声明一一对应。"""

    __tablename__ = "sys_permission"
    __table_args__ = (
        UniqueConstraint("code", name="uk_sys_permission_code"),
        table_comment("权限点表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False, comment="权限码，如 order:release")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="权限名称")
    module: Mapped[str] = mapped_column(String(64), default="", nullable=False,
                                        comment="所属模块")
    is_write: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False,
                                           comment="是否为写操作权限")


class SysUserRole(Base):
    """用户 - 角色关联。"""

    __tablename__ = "sys_user_role"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uk_sys_user_role"),
        table_comment("用户角色关联表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("sys_role.id"), nullable=False)


class SysRolePermission(Base):
    """角色 - 权限关联。"""

    __tablename__ = "sys_role_permission"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uk_sys_role_permission"),
        table_comment("角色权限关联表"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("sys_role.id"), nullable=False)
    permission_id: Mapped[int] = mapped_column(ForeignKey("sys_permission.id"), nullable=False)
