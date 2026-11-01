"""凭据安全存储：DPAPI（CryptProtectData，Current User scope）加密落盘。

文件：%APPDATA%/BlogScreenshotTool/credentials.bin
内容：json.dumps({"username","password","access","refresh"}) 字节经 DPAPI 保护。
解密失败（换用户/文件损坏）一律视为无凭据。
"""
from __future__ import annotations

import ctypes
import json
import logging
from ctypes import wintypes
from pathlib import Path

from app.constants import CREDENTIAL_PATH

CRYPTPROTECT_UI_FORBIDDEN = 0x1
_LOG = logging.getLogger("tray.credentials")


class _DATA_BLOB(ctypes.Structure):
    """Windows CRYPTOAPI BLOB 结构。"""

    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _make_blob(data: bytes) -> _DATA_BLOB:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))


class CredentialStore:
    """登录凭据与 JWT 的 DPAPI 加密存取。"""

    def __init__(self, path: Path = CREDENTIAL_PATH) -> None:
        self._path = Path(path)

    # ---- 对外接口（类图约定） ----
    def save_login(self, username: str, password: str) -> None:
        """保存（或更新）用户名与密码，保留已有 token。"""
        self._update({"username": username, "password": password})

    def load_login(self) -> tuple[str, str] | None:
        """返回 (username, password)，无凭据返回 None。"""
        data = self._read()
        username = str(data.get("username", ""))
        password = str(data.get("password", ""))
        if username and password:
            return username, password
        return None

    def save_tokens(self, access: str, refresh: str) -> None:
        """保存（或更新）JWT，保留已有登录凭据。"""
        self._update({"access": access, "refresh": refresh})

    def load_tokens(self) -> tuple[str, str] | None:
        """返回 (access, refresh)，无 token 返回 None。"""
        data = self._read()
        access = str(data.get("access", ""))
        refresh = str(data.get("refresh", ""))
        if access and refresh:
            return access, refresh
        return None

    def clear_tokens(self) -> None:
        """清空 JWT（刷新失败时调用，下次走密码自动登录）。"""
        self._update({"access": "", "refresh": ""})

    def clear(self) -> None:
        """删除整个凭据文件。"""
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            _LOG.error("删除凭据文件失败：%s", self._path, exc_info=True)

    # ---- 内部 ----
    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            encrypted = self._path.read_bytes()
            plain = self._dpapi_unprotect(encrypted)
            data = json.loads(plain.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _LOG.warning("凭据解密失败，按无凭据处理：%s", self._path, exc_info=True)
            return {}

    def _update(self, patch: dict) -> None:
        data = self._read()
        data.update(patch)
        plain = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(self._dpapi_protect(plain))

    def _dpapi_protect(self, data: bytes) -> bytes:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        blob_in = _make_blob(data)
        blob_out = _DATA_BLOB()
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            "BlogScreenshotTool",
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )
        if not ok:
            raise OSError(f"CryptProtectData failed: {ctypes.get_last_error()}")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def _dpapi_unprotect(self, data: bytes) -> bytes:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        blob_in = _make_blob(data)
        blob_out = _DATA_BLOB()
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )
        if not ok:
            raise OSError(f"CryptUnprotectData failed: {ctypes.get_last_error()}")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
