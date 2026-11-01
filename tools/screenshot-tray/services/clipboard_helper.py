"""剪贴板辅助：复制 Markdown 链接文本。"""
from __future__ import annotations

from PyQt6.QtGui import QGuiApplication


class ClipboardHelper:
    """系统剪贴板读写（Qt 剪贴板，主线程调用）。"""

    @staticmethod
    def copy_text(text: str) -> bool:
        """复制文本到剪贴板，返回是否成功。"""
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(text)
        return True

    @staticmethod
    def last_text() -> str:
        clipboard = QGuiApplication.clipboard()
        return clipboard.text() if clipboard else ""
