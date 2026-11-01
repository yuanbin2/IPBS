"""Long screenshot UI: logical screen selection, bounded worker and session state."""
from __future__ import annotations

import enum
import ctypes
import logging
import threading

from PyQt6.QtCore import QObject, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap, QRegion
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.constants import (
    UI_SCROLL_BTN_CANCEL,
    UI_SCROLL_BTN_FINISH,
    UI_SCROLL_BTN_RETRY,
    UI_SCROLL_COLLECTED,
    UI_SCROLL_FAIL_HINT,
    UI_SCROLL_HINT,
    UI_SCROLL_LIMIT_HINT,
)
from ui.capture_worker import CaptureWorker
from ui.screen_compose import ScreenCapture, compose_selection

_LOG = logging.getLogger("tray.scroll")

# ---- 采集参数 ----
_POLL_INTERVAL_MS = 200     # 抓屏轮询周期
_STABLE_POLLS = 2           # 连续 2 次不变 ≈ 0.4s，判定画面稳定
_CHANGE_THRESHOLD = 3.0     # 降采样平均差 > 此值视为画面变化中（不采集）
# 重复判定阈值（原始分辨率全帧平均通道差）。依据：光标闪烁约占选区
# <0.5% 像素，即使整块反差 255，全帧均值贡献 ≤1.3；亚像素滚动抗锯齿
# 残差约 1~2；合计静态噪声 ≤3。取 4.0 可滤掉全部已知噪声源，而真实
# 滚动（哪怕只挪一行文字）均值 ≥5，留有余量。旧版用降采样图 + 1.2
# 阈值，噪声常超限，导致视觉未滚动的帧被当新帧拼接（重叠=整帧高）。
_DUPLICATE_THRESHOLD = 4.0
_BOTTOM_REPEAT = 2          # 连续 N 次采集到相同画面 → 疑似到底

_PREVIEW_WIDTH = 180
_PREVIEW_HEIGHT = 104
_MARGIN = 8

# ---- 采集范围指示框（PixPin 式：滚动期间选区四周持续可见的边框） ----
# 暖金/琥珀色：深浅背景下都醒目，且不与选区默认蓝边混淆
_INDICATOR_BORDER_COLOR = "#F5A623"
_INDICATOR_BORDER_WIDTH = 2   # 边框线宽（逻辑像素）
_INDICATOR_OUTSET = 4         # 指示窗比选区每边外扩的逻辑像素（≥ 边框线宽）


class _ControlWindow(QWidget):
    """长截图控制窗：拼接预览缩略图、帧数、状态提示、完成/取消（重试）。"""

    finish_clicked = pyqtSignal()
    cancel_clicked = pyqtSignal()  # 取消整轮（按钮非重试态 / closeEvent 关闭窗口）
    retry_clicked = pyqtSignal()   # 「重试」：仅由重试按钮触发，与取消语义分离

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setWindowTitle("长截图")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._retry_mode = False  # 当前按钮语义：True=重试 / False=取消
        self._preview = QLabel(self)
        self._preview.setFixedSize(_PREVIEW_WIDTH, _PREVIEW_HEIGHT)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet("border: 1px solid #2f6fed; background: #ffffff;")
        self._frames_label = QLabel(UI_SCROLL_COLLECTED.format(count=0), self)
        self._status_label = QLabel(UI_SCROLL_HINT, self)
        self._status_label.setWordWrap(True)
        self._status_label.setFixedWidth(_PREVIEW_WIDTH)
        self._finish_button = QPushButton(UI_SCROLL_BTN_FINISH, self)
        self._finish_button.clicked.connect(self.finish_clicked)
        self._cancel_button = QPushButton(UI_SCROLL_BTN_CANCEL, self)
        self._cancel_button.clicked.connect(self._emit_action)
        buttons = QHBoxLayout()
        buttons.addWidget(self._cancel_button)
        buttons.addWidget(self._finish_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        layout.addWidget(self._preview)
        layout.addWidget(self._frames_label)
        layout.addWidget(self._status_label)
        layout.addLayout(buttons)

    # ---- 状态更新（仅主线程调用） ----
    def set_preview(self, image: QImage) -> None:
        """更新拼接预览缩略图（等比缩放进固定尺寸标签）。"""
        scaled = image.scaled(
            _PREVIEW_WIDTH - 4, _PREVIEW_HEIGHT - 4,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._preview.setPixmap(QPixmap.fromImage(scaled))

    def set_frames(self, count: int) -> None:
        self._frames_label.setText(UI_SCROLL_COLLECTED.format(count=count))

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def set_retry_mode(self, enabled: bool) -> None:
        """重试模式：取消按钮临时变为「重试」，点击语义随之切换。"""
        self._retry_mode = enabled
        self._cancel_button.setText(UI_SCROLL_BTN_RETRY if enabled else UI_SCROLL_BTN_CANCEL)

    def _emit_action(self) -> None:
        """按当前按钮语义分发：重试态发 retry_clicked，否则发 cancel_clicked。

        信号拆分的原因：closeEvent（Alt+F4）必须无条件走「取消整轮」，
        若复用 cancel_clicked 信号由控制器按模式解释，重试模式下关窗
        会被误判为「重试」，控制窗已关却恢复采集，形成无 UI 孤儿会话。
        """
        if self._retry_mode:
            self.retry_clicked.emit()
        else:
            self.cancel_clicked.emit()

    def show_near(self, rect: QRect) -> None:
        """Prefer outside selection; when impossible, grab hides the window briefly."""
        self.adjustSize()
        screen = QGuiApplication.screenAt(rect.bottomRight()) or QGuiApplication.primaryScreen()
        if screen is None:
            self.show()
            return
        available = screen.availableGeometry()
        x = rect.right() + _MARGIN
        y = rect.bottom() - self.height()
        if x + self.width() > available.right():
            x = rect.left() - _MARGIN - self.width()
        x = min(max(x, available.left() + _MARGIN), available.right() - self.width() - _MARGIN)
        y = min(max(y, available.top() + _MARGIN), available.bottom() - self.height() - _MARGIN)
        self.setGeometry(x, y, self.width(), self.height())
        self.show()
        self.raise_()
        self._overlaps_selection = self.geometry().intersects(rect)
        _LOG.info("长截图控制窗显示于 (%d, %d)", x, y)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Esc = 完成：拼接结果走去向动作（与「完成」按钮等价）
        if event.key() == Qt.Key.Key_Escape:
            self.finish_clicked.emit()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        # Alt+F4 等关闭视为取消整轮长截图
        self.cancel_clicked.emit()
        event.accept()


class _RegionIndicator(QWidget):
    """单屏采集范围指示框：选区四周持续可见的琥珀色边框环带。

    窗口属性：置顶 + 无边框 + Tool + **WindowTransparentForInput**
    （鼠标与滚轮完全穿透，绝不影响下层页面滚动）；背景全透明，
    **不加深色遮罩**（用户要边滚边看内容）。

    防污染约束（必须维持）：_grab_selection() 用 screen.grabWindow(0)
    抓取选区矩形，本窗口绝不能在选区内部绘制任何像素。实现上：
    - 窗口几何 = 选区每边外扩 _INDICATOR_OUTSET 后与本屏的交集；
    - 边框只画在选区边界之外的环带 [1, _INDICATOR_BORDER_WIDTH] 像素内
      （_INDICATOR_OUTSET ≥ _INDICATOR_BORDER_WIDTH，环带完整落在窗口内）；
    - 选区内部区域保持全透明（alpha=0），grabWindow 抓选区时该区域
      合成为「无内容」，边框又位于抓取矩形之外，故帧不被污染。

    偏移论证（grab 逻辑矩形 × dpr 与边框的关系）：_grab_selection 对每屏
    抓取 intersection = 选区 ∩ 屏幕几何 的逻辑矩形，grabWindow 的取景
    范围即 [intersection.left(), intersection.right()] × [top, bottom]
    （物理像素为其 × dpr）。而边框条带位于选区边界外侧：
    上边带 y ∈ [sel.top()-w, sel.top())、下边带 y ∈ (sel.bottom(), sel.bottom()+w]、
    左边带 x ∈ [sel.left()-w, sel.left())、右边带 x ∈ (sel.right(), sel.right()+w]
    （w = _INDICATOR_BORDER_WIDTH，sel 为全局逻辑选区）。这些开/闭区间与
    抓取矩形 [sel.left(), sel.right()] × [sel.top(), sel.bottom()] 的交集为空，
    数学上保证边框永远落在抓取范围外。

    多屏方案：与 overlay_selector 一致采用「每屏一个窗口」。理由：混排 DPI
    （如 100% + 150%）下，跨屏单窗口的 devicePixelRatio 取决于其所在屏，
    逻辑像素→物理像素换算在不同屏不一致，边框粗细/位置会出现偏差；
    每屏窗口各自 setScreen 后按本屏 dpr 渲染，2 逻辑像素边框在每屏粗细一致。
    """

    def __init__(self, screen, selection: QRect) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput,
        )
        self._screen = screen
        self._selection = QRect(selection)  # 全局逻辑矩形
        self.setScreen(screen)
        expanded = selection.adjusted(
            -_INDICATOR_OUTSET, -_INDICATOR_OUTSET,
            _INDICATOR_OUTSET, _INDICATOR_OUTSET,
        )
        self.setGeometry(expanded.intersected(screen.geometry()))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def paintEvent(self, event) -> None:  # noqa: N802
        # 选区的本屏局部坐标（窗口原点 = 外扩矩形 ∩ 本屏 的左上角）
        local_sel = self._selection.translated(-self.geometry().topLeft())
        painter = QPainter(self)
        # 硬性裁剪：只允许绘制选区之外的区域（防污染的双保险，
        # 即便下方矩形计算有误，选区内部也不可能被画上任何像素）
        painter.setClipRegion(QRegion(self.rect()).subtracted(QRegion(local_sel)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setBrush(QColor(_INDICATOR_BORDER_COLOR))
        w = _INDICATOR_BORDER_WIDTH
        # 四条边带（上/下边带含四角），全部位于 local_sel 之外
        painter.drawRect(local_sel.left() - w, local_sel.top() - w,
                         local_sel.width() + 2 * w, w)                       # 上
        painter.drawRect(local_sel.left() - w, local_sel.bottom() + 1,
                         local_sel.width() + 2 * w, w)                       # 下
        painter.drawRect(local_sel.left() - w, local_sel.top(),
                         w, local_sel.height())                              # 左
        painter.drawRect(local_sel.right() + 1, local_sel.top(),
                         w, local_sel.height())                              # 右
        painter.end()


class _CaptureState(enum.Enum):
    IDLE = "idle"
    CAPTURING = "capturing"
    PAUSED = "paused"
    RECOVERING = "recovering"
    FINISHING = "finishing"
    CANCELLED = "cancelled"


class ScrollCaptureController(QObject):
    """长截图会话编排：控制窗 + 抓屏定时器 + 后台拼接线程。

    对外契约（AppController 使用）：
    - start(rect)：选区固定后启动（rect 为全局逻辑矩形）；
    - finished(QImage)：点「完成」/Esc → 拼接结果（空结果发 cancelled）；
    - cancelled()：取消整轮；
    - abort()：无声中止（应用退出时调用，不发信号）。
    """

    finished = pyqtSignal(QImage)
    cancelled = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rect = QRect()
        self._window = _ControlWindow()
        self._window.finish_clicked.connect(self.finish)
        self._window.cancel_clicked.connect(self._on_cancel_clicked)
        self._window.retry_clicked.connect(self._on_retry_clicked)
        self._indicators: list[_RegionIndicator] = []
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._grab_frame)
        self._worker = CaptureWorker(self)
        self._worker.frame_collected.connect(self._on_frame_collected)
        self._worker.bottom_detected.connect(self._on_bottom_detected)
        self._worker.failed.connect(self._on_failed)
        self._worker.limit_reached.connect(self._on_limit_reached)
        self._worker.result_ready.connect(self._on_result_ready)
        self._thread: threading.Thread | None = None
        self._paused = False
        self._retry_mode = False
        self._finishing = False
        self._state = _CaptureState.IDLE
        self._escape_filter = None
        self._escape_registered = False

    # ---- 生命周期 ----
    def start(self, rect: QRect) -> None:
        if self._state is not _CaptureState.IDLE:
            return
        self._rect = QRect(rect)
        self._window.set_frames(0)
        self._window.set_status(UI_SCROLL_HINT)
        self._window.show_near(rect)
        self._show_indicators(rect)
        self._thread = threading.Thread(target=self._worker.run, name="scroll-capture", daemon=True)
        self._thread.start()
        self._timer.start()
        self._state = _CaptureState.CAPTURING
        self._register_escape()
        _LOG.info("采集状态 idle -> capturing；选区=%s", rect)

    def finish(self) -> None:
        """点「完成」或 Esc：停止抓屏，取拼接结果。"""
        if self._state in (_CaptureState.FINISHING, _CaptureState.CANCELLED, _CaptureState.IDLE):
            return
        self._finishing = True
        self._state = _CaptureState.FINISHING
        _LOG.info("采集状态 -> finishing；有限等待末帧 650ms")
        self._window.hide()
        self._hide_indicators()
        self._worker.request_result()

    def abort(self) -> None:
        """无声中止（应用退出），不发任何信号。"""
        self._teardown()
        self._await_thread_then(self.deleteLater)

    # ---- 采集范围指示框（仅主线程） ----
    def _show_indicators(self, rect: QRect) -> None:
        """为每个与选区（外扩后）相交的屏幕创建并显示一个指示框窗口。"""
        self._hide_indicators()
        expanded = rect.adjusted(
            -_INDICATOR_OUTSET, -_INDICATOR_OUTSET,
            _INDICATOR_OUTSET, _INDICATOR_OUTSET,
        )
        for screen in QGuiApplication.screens():
            if expanded.intersected(screen.geometry()).isEmpty():
                continue
            indicator = _RegionIndicator(screen, rect)
            self._indicators.append(indicator)
            indicator.show()
            indicator.raise_()
        _LOG.info("长截图范围指示框已显示：选区 %s，窗口数 %d", rect, len(self._indicators))

    def _hide_indicators(self) -> None:
        """隐藏并销毁全部指示框窗口（结束/取消/中止时调用）。"""
        for indicator in self._indicators:
            indicator.hide()
            indicator.deleteLater()
        self._indicators.clear()

    # ---- 抓屏（主线程） ----
    def _grab_frame(self) -> None:
        if self._paused:
            return
        image = self._grab_selection()
        if image is not None and not image.isNull():
            if not self._worker.submit_frame(image) and not self._finishing:
                self._window.set_status("处理暂时落后；请分段停顿，保留重叠区域")

    def _grab_selection(self) -> QImage | None:
        """抓完整屏幕后按共享映射裁剪，输出固定 DPR=1。"""
        # When no outside location fits, hide the control window for the exact
        # grab. It is shown again immediately and remains keyboard/mouse usable.
        hidden = self._window.isVisible() and getattr(self._window, "_overlaps_selection", False)
        if hidden:
            self._window.hide()
            QGuiApplication.processEvents()
        captures: list[ScreenCapture] = []
        for screen in QGuiApplication.screens():
            if not self._rect.intersects(screen.geometry()):
                continue
            pixmap = screen.grabWindow(0)
            captures.append(ScreenCapture(screen.geometry(), pixmap.toImage(), pixmap.devicePixelRatio() or 1.0))
        anchor = next((c for c in captures if c.geometry.contains(self._rect.topLeft())), None)
        if anchor is None:
            anchor = next((c for c in captures if c.geometry.intersects(self._rect)), None)
        result = compose_selection(self._rect, captures, anchor.dpr if anchor else 1.0)
        if hidden and not self._finishing:
            self._window.show()
        return result

    # ---- 工作线程信号（跨线程自动排队回主线程） ----
    def _on_frame_collected(self, generation: int, count: int, canvas: QImage) -> None:
        if generation != self._worker.generation or self._state not in (_CaptureState.CAPTURING, _CaptureState.RECOVERING):
            return
        self._state = _CaptureState.CAPTURING
        if self._retry_mode:
            self._retry_mode = False
            self._window.set_retry_mode(False)
        self._window.set_frames(count)
        self._window.set_preview(canvas)
        self._window.set_status(UI_SCROLL_HINT)

    def _on_bottom_detected(self, generation: int) -> None:
        if generation != self._worker.generation or self._state not in (_CaptureState.CAPTURING, _CaptureState.RECOVERING):
            return
        if not self._retry_mode:
            self._window.set_status("画面暂无变化；继续滚动或点「完成」")

    def _on_failed(self, generation: int, reason: str, message: str) -> None:
        if generation != self._worker.generation or self._state not in (_CaptureState.CAPTURING, _CaptureState.RECOVERING):
            return
        """无重叠等可重试失败：暂停抓屏，控制窗提供「重试 / 完成」。"""
        _LOG.warning("长截图拼接失败：reason=%s", reason)
        self._timer.stop()
        self._worker.pause()
        self._state = _CaptureState.PAUSED
        self._paused = True
        self._retry_mode = True
        self._window.set_retry_mode(True)
        self._window.set_status(UI_SCROLL_FAIL_HINT.format(message=message))

    def _on_limit_reached(self, generation: int, message: str) -> None:
        if generation != self._worker.generation or self._state not in (_CaptureState.CAPTURING, _CaptureState.RECOVERING):
            return
        """达上限：自动暂停抓屏，提示点「完成」。"""
        _LOG.info("长截图达上限：%s", message)
        self._timer.stop()
        self._worker.pause()
        self._state = _CaptureState.PAUSED
        self._paused = True
        self._window.set_status(UI_SCROLL_LIMIT_HINT.format(message=message))

    def _on_result_ready(self, generation: int, image: QImage) -> None:
        if generation != self._worker.generation or self._state is not _CaptureState.FINISHING:
            return
        self._timer.stop()
        self._window.hide()
        self._hide_indicators()
        self._await_thread_then(lambda: self._emit_result(image))

    def _emit_result(self, image: QImage) -> None:
        if self._state is not _CaptureState.FINISHING:
            return
        self._unregister_escape()
        if image.isNull() or image.width() == 0 or image.height() == 0:
            self.cancelled.emit()
            return
        self.finished.emit(image)

    # ---- 取消 / 重试 ----
    def _on_cancel_clicked(self) -> None:
        # 取消整轮：控制窗「取消」按钮、Alt+F4 / closeEvent 均走到这里
        self._teardown()
        self._await_thread_then(self.cancelled.emit)

    def _on_retry_clicked(self) -> None:
        if self._state is not _CaptureState.PAUSED:
            return
        # 「重试」：恢复抓屏，帧间状态清空（画布保留），用户继续滚动
        self._retry_mode = False
        self._paused = False
        self._window.set_retry_mode(False)
        self._worker.reset_session()
        self._state = _CaptureState.RECOVERING
        _LOG.info("采集状态 paused -> recovering generation=%d", self._worker.generation)
        self._window.set_status(UI_SCROLL_HINT)
        self._timer.start()

    def _teardown(self) -> None:
        if self._state is _CaptureState.CANCELLED:
            return
        self._state = _CaptureState.CANCELLED
        self._timer.stop()
        self._paused = True  # 防止残留定时器再投帧
        self._window.hide()
        self._hide_indicators()
        self._worker.stop()
        self._unregister_escape()
        _LOG.info("采集状态 cancelled；等待线程异步结束")

    def _register_escape(self) -> None:
        if not hasattr(ctypes, "WinDLL"):
            return
        from services.hotkey_manager import HotkeyNativeFilter
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if user32.RegisterHotKey(None, 0xB10D, 0, 0x1B):
            self._escape_filter = HotkeyNativeFilter(0xB10D, self.finish)
            QGuiApplication.instance().installNativeEventFilter(self._escape_filter)
            self._escape_registered = True
        else:
            _LOG.warning("长截图会话 Esc 全局热键注册失败 error=%s", ctypes.get_last_error())

    def _unregister_escape(self) -> None:
        if self._escape_filter is not None:
            QGuiApplication.instance().removeNativeEventFilter(self._escape_filter)
            self._escape_filter = None
        if self._escape_registered:
            ctypes.WinDLL("user32", use_last_error=True).UnregisterHotKey(None, 0xB10D)
            self._escape_registered = False

    def _await_thread_then(self, callback) -> None:
        if self._thread is not None and self._thread.is_alive():
            QTimer.singleShot(20, lambda: self._await_thread_then(callback))
            return
        self._thread = None
        callback()
