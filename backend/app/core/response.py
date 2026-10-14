"""统一响应结构。

所有 RESTful 接口统一返回::

    {"code": 0, "msg": "success", "data": {...}}

业务失败时 code 取非零业务码，HTTP 状态码保持语义正确；
参数校验失败时返回可读的字段级错误描述，而不是裸露的 Pydantic 内部结构。
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

CODE_SUCCESS = 0
CODE_BUSINESS_ERROR = 4000      # 业务规则不满足
CODE_FORBIDDEN = 4003           # 无接口权限
CODE_NOT_FOUND = 4004
CODE_CONFLICT = 4009            # 状态机冲突 / 幂等冲突


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应体（同时作为 OpenAPI 文档模型）。"""

    code: int = Field(CODE_SUCCESS, description="业务状态码，0 表示成功")
    msg: str = Field("success", description="可读提示信息")
    data: Optional[T] = Field(None, description="业务数据")


class PageData(BaseModel, Generic[T]):
    """分页包装结构，所有列表查询接口统一使用。"""

    items: list[T] = Field(default_factory=list, description="当前页数据")
    total: int = Field(0, description="总记录数")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(20, description="每页条数")
    pages: int = Field(0, description="总页数")


def ok(data: Any = None, msg: str = "success", code: int = CODE_SUCCESS) -> dict:
    """构造成功响应。"""
    return {"code": code, "msg": msg, "data": data}


def fail(msg: str, code: int = CODE_BUSINESS_ERROR, data: Any = None) -> dict:
    """构造失败响应。"""
    return {"code": code, "msg": msg, "data": data}


def page_of(items: list, total: int, page: int, page_size: int) -> dict:
    """构造分页结果。"""
    pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }
