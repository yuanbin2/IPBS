"""工具异常体系：所有可预期失败都携带错误码与用户可读文案。"""
from __future__ import annotations


class ToolError(Exception):
    """基础异常。code 用于日志与分支判断，message 直接展示给用户。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthError(ToolError):
    """登录态问题：未登录、凭据无效、刷新失败。"""

    def __init__(self, message: str) -> None:
        super().__init__("auth", message)


class UploadError(ToolError):
    """上传失败：超限、限流、无权限、后端不可用等。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


class NetworkError(ToolError):
    """网络问题：连接失败、超时。"""

    def __init__(self, message: str) -> None:
        super().__init__("network", message)
