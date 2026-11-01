"""托盘图标与菜单：截图 / 打开设置 / 开机自启 / 退出。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from app.constants import (
    UI_TOOL_TIP,
    UI_TRAY_AUTOSTART,
    UI_TRAY_CAPTURE,
    UI_TRAY_QUIT,
    UI_TRAY_SCROLL_CAPTURE,
    UI_TRAY_SETTINGS,
)

_LOG = logging.getLogger("tray.tray")


def _make_icon() -> QIcon:
    """程序化绘制托盘图标（无外部资源依赖）。"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2f6fed"))
    painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
    painter.setPen(QColor("white"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(30)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "截")
    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    """系统托盘入口。用户动作通过信号交由 AppController 处理。"""

    capture_requested = pyqtSignal()
    scroll_capture_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    autostart_changed = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(_make_icon(), parent)
        self.setToolTip(UI_TOOL_TIP)
        menu = QMenu()
        self._capture_action = QAction(UI_TRAY_CAPTURE, menu)
        self._scroll_capture_action = QAction(UI_TRAY_SCROLL_CAPTURE, menu)
        self._settings_action = QAction(UI_TRAY_SETTINGS, menu)
        self._autostart_action = QAction(UI_TRAY_AUTOSTART, menu)
        self._autostart_action.setCheckable(True)
        self._quit_action = QAction(UI_TRAY_QUIT, menu)
        menu.addAction(self._capture_action)
        menu.addAction(self._scroll_capture_action)
        menu.addSeparator()
        menu.addAction(self._settings_action)
        menu.addAction(self._autostart_action)
        menu.addSeparator()
        menu.addAction(self._quit_action)
        self.setContextMenu(menu)
        # 信号 → 信号直连，控制器负责具体分发
        self._capture_action.triggered.connect(self.capture_requested)
        self._scroll_capture_action.triggered.connect(self.scroll_capture_requested)
        self._settings_action.triggered.connect(self.settings_requested)
        self._quit_action.triggered.connect(self.quit_requested)
        self._autostart_action.toggled.connect(self.autostart_changed)
        self.capture_requested.connect(self._log_capture)

    def show(self) -> None:  # noqa: D102（覆盖父类无实现的方法）
        super().show()
        _LOG.info("托盘图标已显示")

    def set_autostart_checked(self, enabled: bool) -> None:
        """同步自启菜单勾选状态（不回发信号）。"""
        self._autostart_action.setChecked(enabled)

    def update_hotkey_hint(self, hotkey: str) -> None:
        """更新菜单里截图项的热键提示。"""
        self._capture_action.setText(f"{UI_TRAY_CAPTURE}（{hotkey}）")

    def _log_capture(self) -> None:
        _LOG.info("托盘菜单触发截图")
