"""DRF 全局异常处理：把异常统一成 {"detail", "code"} 错误格式。

配套 ``views/common.py`` 的 ``error_response()``：手写错误响应用 error_response，
未手动处理的 DRF 异常走本模块的 exception_handler（settings 中
REST_FRAMEWORK["EXCEPTION_HANDLER"] 接线）。``detail`` 给人看，``code`` 给前端
做程序化分支；新增 code 字段是向后兼容的，不影响既有前端。
"""

from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler as drf_exception_handler


class ErrorCode:
    """错误码枚举（约定见 coding-conventions.md §4.4）。"""

    MISSING_FIELD = "missing_field"
    VALIDATION_ERROR = "validation_error"
    NOT_AUTHENTICATED = "not_authenticated"
    INVALID_CREDENTIALS = "invalid_credentials"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    INTERNAL_ERROR = "internal_error"


_STATUS_CODE_MAP = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.NOT_AUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.VALIDATION_ERROR,
    409: ErrorCode.CONFLICT,
    429: ErrorCode.RATE_LIMITED,
    502: ErrorCode.UPSTREAM_UNAVAILABLE,
    503: ErrorCode.UPSTREAM_UNAVAILABLE,
}


def exception_handler(exc, context):
    """把 DRF 异常规范化成 {"detail", "code"}；非 DRF 异常交回默认 500 处理链。"""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, ValidationError):
        # 字段级校验错误保留原结构（列表/字典），仅标注 code
        response.data = {"detail": response.data, "code": ErrorCode.VALIDATION_ERROR}
        return response

    detail = response.data.get("detail") if isinstance(response.data, dict) else None
    response.data = {
        "detail": detail or "请求处理失败",
        "code": _STATUS_CODE_MAP.get(response.status_code, ErrorCode.INTERNAL_ERROR),
    }
    return response
