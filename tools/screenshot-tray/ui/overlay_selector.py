"""全屏遮罩选区：每屏一个无边框窗口，支持跨屏拖拽，按物理像素裁剪。

要点（docs/system_design.md T03 验收）：
- 每屏一个遮罩窗口，Qt6 默认 per-monitor DPI aware；
- 拖拽跨屏时由选择器统一维护全局逻辑坐标矩形，各窗口绘制各自交集；
- 裁剪用设备像素（QPixmap.devicePixelRatio 换算），保证混排缩放（100%/150%）下颜色不错位；
- Esc 取消；选区过小视为取消。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QEventLoop, QObject, QPoint, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget
from ui.screen_compose import ScreenCapture, compose_selection

_LOG = logging.getLogger("tray.overlay")

_MIN_SELECTION_SIZE = 2  # 逻辑像素，小于此视为误点击


class _ScreenOverlay(QWidget):
    """单屏遮罩窗口。事件坐标一律转成全局逻辑坐标上报。"""

    started = pyqtSignal(QPoint)
    moved = pyqtSignal(QPoint)
    released = pyqtSignal(QPoint)
    cancelled = pyqtSignal()

    def __init__(self, screen, shot: QPixmap) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._screen = screen
        self._shot = shot
        self._selection = QRect()
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_selection(self, rect: QRect) -> None:
        self._selection = rect
        self.update()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        image = self._shot.toImage()
        target = QRectF(self.rect())
        # 半透明遮罩盖住整屏
        painter.drawImage(target, image)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        # 选区内重绘原始图像（去掉遮罩），并描边
        geometry = self.geometry()
        intersection = self._selection.intersected(geometry)
        if not intersection.isEmpty():
            local = intersection.translated(-geometry.topLeft())
            painter.setClipRect(QRectF(local))
            painter.drawImage(target, image)
            painter.setClipping(False)
            painter.setPen(QPen(QColor(0, 174, 255), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(local)

    # ---- 事件（转全局逻辑坐标） ----
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.started.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.moved.emit(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.released.emit(event.globalPosition().toPoint())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()


class OverlaySelector(QObject):
    """选区控制器：管理每屏遮罩窗口、全局选区矩形与物理像素合成。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._overlays: list[_ScreenOverlay] = []
        self._shots: list[QPixmap] = []
        self._origin: QPoint | None = None
        self._current = QRect()
        self._last_rect: QRect | None = None
        self._loop: QEventLoop | None = None
        self._result: QImage | None = None

    def last_selection_rect(self) -> QRect | None:
        """最近一次有效选区的全局逻辑矩形（供悬浮条定位）。"""
        return self._last_rect

    # ---- 对外接口（类图约定：run(monitor_shots) -> QImage | None） ----
    def run(self, monitor_shots: list[QPixmap]) -> QImage | None:
        """弹出每屏遮罩进入模态选区。确认返回物理像素 QImage，取消返回 None。

        monitor_shots 顺序必须与 QGuiApplication.screens() 一致
        （调用方按 screens() 顺序 grabWindow(0) 即满足）。
        """
        screens = QGuiApplication.screens()
        if len(monitor_shots) != len(screens):
            _LOG.error("monitor_shots 数量(%d)与屏幕数量(%d)不一致", len(monitor_shots), len(screens))
            return None
        self._shots = list(monitor_shots)
        self._origin = None
        self._current = QRect()
        self._result = None
        self._loop = QEventLoop()
        self._overlays = []
        for screen, shot in zip(screens, self._shots):
            overlay = _ScreenOverlay(screen, shot)
            overlay.started.connect(self._on_started)
            overlay.moved.connect(self._on_moved)
            overlay.released.connect(self._on_released)
            overlay.cancelled.connect(self._on_cancelled)
            self._overlays.append(overlay)
        for overlay in self._overlays:
            overlay.show()
            overlay.raise_()
            overlay.activateWindow()
        self._loop.exec()
        return self._result

    # ---- 选区状态 ----
    def _on_started(self, pos: QPoint) -> None:
        self._origin = pos
        self._update(pos)

    def _on_moved(self, pos: QPoint) -> None:
        if self._origin is not None:
            self._update(pos)

    def _update(self, pos: QPoint) -> None:
        if self._origin is None:
            return
        self._current = QRect(self._origin, pos).normalized()
        for overlay in self._overlays:
            overlay.set_selection(self._current)

    def _on_released(self, pos: QPoint) -> None:
        self._update(pos)
        self._finish(self._compose(self._current))

    def _on_cancelled(self) -> None:
        _LOG.info("选区取消（Esc）")
        self._finish(None)

    def _finish(self, image: QImage | None) -> None:
        if image is not None:
            self._last_rect = QRect(self._current)
        for overlay in self._overlays:
            overlay.close()
            overlay.deleteLater()
        self._overlays.clear()
        self._origin = None
        self._result = image
        if self._loop is not None:
            self._loop.quit()
            self._loop = None

    # ---- 物理像素合成 ----
    def _compose(self, rect: QRect) -> QImage | None:
        """所有屏幕使用选区起点所在屏的输出 DPR。"""
        if rect is None or rect.width() < _MIN_SELECTION_SIZE or rect.height() < _MIN_SELECTION_SIZE:
            return None
        screens = QGuiApplication.screens()
        captures = [ScreenCapture(screen.geometry(), shot.toImage(), shot.devicePixelRatio() or 1.0)
                    for screen, shot in zip(screens, self._shots)]
        anchor = next((c for c in captures if c.geometry.contains(rect.topLeft())), None)
        if anchor is None:
            anchor = next((c for c in captures if c.geometry.intersects(rect)), None)
        result = compose_selection(rect, captures, anchor.dpr if anchor else 1.0)
        if result is not None:
            _LOG.info("选区完成：逻辑 %s → 设备 %dx%d DPR=%.2f", rect, result.width(), result.height(), anchor.dpr)
        return result
