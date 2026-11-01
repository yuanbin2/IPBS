"""成功/失败提示气泡（基于 QSystemTrayIcon.showMessage 原生气泡）。"""
from __future__ import annotations

from PyQt6.QtWidgets import QSystemTrayIcon

_TOAST_TIMEOUT_MS = 4000


class Toast:
    """托盘气泡提示封装。success/info/error 三档图标；可按条覆盖展示时长。"""

    def __init__(self, tray: QSystemTrayIcon, timeout_ms: int = _TOAST_TIMEOUT_MS) -> None:
        self._tray = tray
        self._timeout = timeout_ms

    def success(self, text: str, timeout_ms: int | None = None) -> None:
        self._tray.showMessage(
            "截图工具", text, QSystemTrayIcon.MessageIcon.Information,
            self._timeout if timeout_ms is None else timeout_ms,
        )

    def info(self, text: str, timeout_ms: int | None = None) -> None:
        self._tray.showMessage(
            "截图工具", text, QSystemTrayIcon.MessageIcon.Information,
            self._timeout if timeout_ms is None else timeout_ms,
        )

    def error(self, text: str, timeout_ms: int | None = None) -> None:
        self._tray.showMessage(
            "截图工具", text, QSystemTrayIcon.MessageIcon.Critical,
            self._timeout if timeout_ms is None else timeout_ms,
        )
