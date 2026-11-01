"""悬浮操作条：发博客 / 存本地 / OCR 识别 / 长截图 / 取消。

定位在选区右下角外侧并夹紧在所在屏内（不越屏）；任一动作点击后自动隐藏
（设计 §5.1：动作发起即隐藏，失败回退后气泡提示并结束本轮）。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from app.constants import (
    UI_BTN_CANCEL,
    UI_BTN_OCR,
    UI_BTN_PUBLISH,
    UI_BTN_SAVE,
    UI_BTN_SCROLL,
)

_LOG = logging.getLogger("tray.toolbar")

_MARGIN = 8


class ActionToolbar(QWidget):
    """截图后浮在选区旁的操作条。动作通过信号交由 AppController 分发。"""

    publish_clicked = pyqtSignal()
    save_local_clicked = pyqtSignal()
    ocr_clicked = pyqtSignal()
    scroll_capture_clicked = pyqtSignal()
    cancel_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        for text, signal in (
            (UI_BTN_PUBLISH, self.publish_clicked),
            (UI_BTN_SAVE, self.save_local_clicked),
            (UI_BTN_OCR, self.ocr_clicked),
            (UI_BTN_SCROLL, self.scroll_capture_clicked),
            (UI_BTN_CANCEL, self.cancel_clicked),
        ):
            button = QPushButton(text, self)
            button.clicked.connect(self._make_emit(signal))
            layout.addWidget(button)

    @staticmethod
    def _make_emit(signal):
        def _emit() -> None:
            # 动作发起即隐藏（设计 §5.1）
            signal.emit()

        return _emit

    def show_near(self, rect: QRect) -> None:
        """显示在选区右下角外侧；越出所在屏时收回到屏内。"""
        self.adjustSize()
        screen = QGuiApplication.screenAt(rect.bottomRight()) or QGuiApplication.primaryScreen()
        if screen is None:
            self.show()
            return
        available = screen.availableGeometry()
        x = rect.right() - self.width()
        y = rect.bottom() + _MARGIN
        if y + self.height() > available.bottom():
            # 放不下了就贴选区上缘上方
            y = rect.top() - _MARGIN - self.height()
        x = min(max(x, available.left() + _MARGIN), available.right() - self.width() - _MARGIN)
        y = min(max(y, available.top() + _MARGIN), available.bottom() - self.height() - _MARGIN)
        self.setGeometry(x, y, self.width(), self.height())
        self.show()
        self.raise_()
        self.activateWindow()
        _LOG.info("悬浮条显示于 (%d, %d)", x, y)
