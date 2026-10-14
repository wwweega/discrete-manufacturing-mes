"""业务异常体系。

服务层只抛 BusinessError 及其子类，由全局异常处理器翻译成统一响应结构，
HTTP 状态码由异常自身携带，保证「业务码可读 + HTTP 语义正确」。
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.core.response import (
    CODE_BUSINESS_ERROR,
    CODE_CONFLICT,
    CODE_FORBIDDEN,
    CODE_NOT_FOUND,
)


class BusinessError(HTTPException):
    """带业务码的业务异常基类。"""

    http_status: int = status.HTTP_400_BAD_REQUEST
    biz_code: int = CODE_BUSINESS_ERROR

    def __init__(self, msg: str, code: int | None = None, **kwargs):
        detail = {"code": code if code is not None else self.biz_code, "msg": msg, "data": None}
        super().__init__(status_code=self.http_status, detail=detail)


class NotFoundError(BusinessError):
    http_status = status.HTTP_404_NOT_FOUND
    biz_code = CODE_NOT_FOUND


class ForbiddenError(BusinessError):
    http_status = status.HTTP_403_FORBIDDEN
    biz_code = CODE_FORBIDDEN


class StateConflictError(BusinessError):
    """状态机非法流转。"""

    http_status = status.HTTP_409_CONFLICT
    biz_code = CODE_CONFLICT


class DuplicateReportError(BusinessError):
    """重复报工（幂等拦截）。"""

    http_status = status.HTTP_409_CONFLICT
    biz_code = CODE_CONFLICT


class InventoryShortageError(BusinessError):
    """库存不足。"""

    http_status = status.HTTP_409_CONFLICT
    biz_code = CODE_CONFLICT


class UnauthorizedError(BusinessError):
    http_status = status.HTTP_401_UNAUTHORIZED
    biz_code = CODE_FORBIDDEN
