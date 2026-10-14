"""通用 Schema：分页、登录、统一消息。"""

from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """支持从 ORM 对象直接序列化的基类。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Pagination(BaseModel):
    page: int = Field(1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(20, ge=1, le=200, description="每页条数")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int = 0
    page: int = 1
    page_size: int = 20
    pages: int = 0


class LoginRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "username": "admin", "password": "mes@2026"
    }})

    username: str = Field(..., min_length=1, max_length=64, description="登录账号",
                          examples=["admin"])
    password: str = Field(..., min_length=1, max_length=128, description="密码",
                          examples=["mes@2026"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="有效期（秒）")
    username: str
    real_name: str
    roles: list[str]
    permissions: list[str]


class MessageResponse(BaseModel):
    """简单消息响应，用于无数据返回的写接口。"""

    detail: str
    success: bool = True
