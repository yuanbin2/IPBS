"""AppController：全局编排与状态机（热键 → 遮罩 → 悬浮条 → 动作分发）。

状态流转（docs/system_design.md §4 时序）：
- 空闲 --hotkey--> 选区 --确认--> 待处理（悬浮条）--动作--> 空闲
- 任何上传失败 → fallback_save_local（回退存本地 + 气泡）→ 空闲
"""
from __future__ import annotations

import logging
import sys
import threading
import winreg
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, QObject, QRect, pyqtSignal
from PyQt6.QtGui import QImage, QGuiApplication
from PyQt6.QtWidgets import QApplication

from app.constants import (
    AUTOSTART_RUN_KEY,
    AUTOSTART_VALUE_NAME,
    HANDOFF_MAX_BYTES,
    TIMESTAMP_FORMAT,
    UI_TOAST_AUTH_GUIDE,
    UI_TOAST_AUTH_TIMEOUT_MS,
    UI_TOAST_BUSY,
    UI_TOAST_COPY_OK,
    UI_TOAST_FALLBACK,
    UI_TOAST_FALLBACK_AUTH,
    UI_TOAST_HOTKEY_FAILED,
    UI_TOAST_OCR_OPENED,
    UI_TOAST_PNG_ENCODE_FAILED,
    UI_TOAST_SAVE_FAILED,
    UI_TOAST_SAVED,
    UI_TOAST_SCROLL_DONE,
    UI_TOAST_SETTINGS_SAVED,
    UI_TOAST_STARTED,
    UI_TOAST_UPLOADING,
)
from app.errors import ToolError
from core.config_store import ConfigStore
from core.credential_store import CredentialStore
from handoff.handoff_server import HandoffServer
from services.auth_client import AuthClient
from services.blog_api_client import BlogApiClient
from services.clipboard_helper import ClipboardHelper
from services.hotkey_manager import HotkeyManager
from services.local_saver import LocalSaver
from ui.action_toolbar import ActionToolbar
from ui.overlay_selector import OverlaySelector
from ui.scroll_capture import ScrollCaptureController
from ui.settings_dialog import SettingsDialog
from ui.toast import Toast
from ui.tray_icon import TrayIcon

_LOG = logging.getLogger("tray.controller")


class AppController(QObject):
    """单例主控制器：装配各层组件并编排 P0/P1 全链路。"""

    # 后台上传线程 → 主线程（跨线程自动排队连接）
    _publish_ok = pyqtSignal(str)
    _publish_failed = pyqtSignal(str, str)  # 用户可读消息, 错误码

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._config = ConfigStore()
        self._credentials = CredentialStore()
        self._auth = AuthClient(self._config, self._credentials)
        self._api = BlogApiClient(self._config, self._auth)
        self._saver = LocalSaver(self._config)
        self._clipboard = ClipboardHelper()
        self._hotkey = HotkeyManager(self)
        self._overlay = OverlaySelector(self)
        self._toolbar = ActionToolbar()
        self._tray = TrayIcon()
        self._toast = Toast(self._tray)
        self._handoff = HandoffServer()
        self._shot: QImage | None = None
        self._scroll: ScrollCaptureController | None = None

        self._toolbar.publish_clicked.connect(self.on_publish)
        self._toolbar.save_local_clicked.connect(self.on_save_local)
        self._toolbar.ocr_clicked.connect(self.on_ocr_handoff)
        self._toolbar.scroll_capture_clicked.connect(self.on_start_scroll_capture)
        self._toolbar.cancel_clicked.connect(self._on_capture_cancelled)
        self._tray.capture_requested.connect(self.on_hotkey)
        self._tray.scroll_capture_requested.connect(self.on_scroll_capture)
        self._tray.settings_requested.connect(self.open_settings)
        self._tray.quit_requested.connect(self.quit)
        self._tray.autostart_changed.connect(self._on_autostart_toggled)
        self._publish_ok.connect(self._on_publish_ok)
        self._publish_failed.connect(self._on_publish_failed)

    # ---- 生命周期 ----
    def start(self) -> None:
        """显示托盘并注册热键。"""
        self._tray.show()
        self._tray.set_autostart_checked(self._config.autostart)
        hotkey = self._config.hotkey
        if self._hotkey.register(hotkey, self.on_hotkey):
            self._tray.update_hotkey_hint(hotkey)
            self._toast.info(UI_TOAST_STARTED.format(hotkey=hotkey))
        else:
            self._tray.update_hotkey_hint(f"{hotkey}（注册失败）")
            self._toast.error(UI_TOAST_HOTKEY_FAILED.format(hotkey=hotkey))
        _LOG.info("AppController 启动完成")

    def quit(self) -> None:
        """清理资源后退出（托盘菜单「退出」）。"""
        _LOG.info("退出：注销热键、关闭交接端点")
        self._hotkey.unregister()
        if self._scroll is not None:
            self._scroll.abort()
            self._scroll = None
        self._handoff.stop()
        self._toolbar.hide()
        self._tray.hide()
        self._app.quit()

    # ---- 截图主链路 ----
    def on_hotkey(self) -> None:
        """热键/菜单触发：抓各屏 → 遮罩选区 → 进入待处理状态。"""
        if self._busy():
            self._toast.info(UI_TOAST_BUSY)
            return
        _LOG.info("热键触发，开始抓屏")
        # 先抓屏再弹遮罩，保证遮罩不进画面
        shot = self._capture_selection()
        if shot is None:
            _LOG.info("本轮截图取消")
            return
        self.on_captured(shot)

    def on_scroll_capture(self) -> None:
        """托盘菜单「长截图」：选区后直接进入滚动采集。"""
        if self._busy():
            self._toast.info(UI_TOAST_BUSY)
            return
        _LOG.info("托盘菜单触发长截图")
        shot = self._capture_selection()
        if shot is None:
            return
        self._shot = shot
        self._begin_scroll_capture()

    def _capture_selection(self) -> QImage | None:
        """抓各屏 → 遮罩选区，返回物理像素 QImage（取消返回 None）。"""
        shots = [screen.grabWindow(0) for screen in QGuiApplication.screens()]
        return self._overlay.run(shots)

    def _busy(self) -> bool:
        """有截图待处理或长截图会话进行中。"""
        return self._shot is not None or self._scroll is not None

    def on_captured(self, shot: QImage) -> None:
        """选区完成：暂存截图并弹出悬浮条。"""
        self._shot = shot
        rect = self._overlay.last_selection_rect()
        if rect is None:
            screen = QGuiApplication.primaryScreen()
            rect = screen.availableGeometry() if screen else QRect(100, 100, 400, 300)
        self._toolbar.show_near(rect)
        _LOG.info("截图就绪：%dx%d，等待动作", shot.width(), shot.height())

    def _on_capture_cancelled(self) -> None:
        self._toolbar.hide()
        self._shot = None
        _LOG.info("悬浮条取消，本轮结束")

    # ---- 长截图（滚动截图） ----
    def on_start_scroll_capture(self) -> None:
        """悬浮条「长截图」按钮：以当前截图选区进入滚动采集。"""
        if self._shot is None or self._scroll is not None:
            return
        self._toolbar.hide()
        self._begin_scroll_capture()

    def _begin_scroll_capture(self) -> None:
        rect = self._overlay.last_selection_rect()
        if rect is None:
            screen = QGuiApplication.primaryScreen()
            rect = screen.availableGeometry() if screen else QRect(100, 100, 400, 300)
        self._scroll = ScrollCaptureController(self)
        self._scroll.finished.connect(self._on_scroll_finished)
        self._scroll.cancelled.connect(self._on_scroll_cancelled)
        self._scroll.start(rect)
        _LOG.info("长截图开始：选区 %s", rect)

    def _on_scroll_finished(self, image: QImage) -> None:
        """拼接完成：结果作为一张图回到悬浮条，走与普通截图同一套去向动作。"""
        if self._scroll is not None:
            self._scroll.deleteLater()
            self._scroll = None
        self._shot = image
        rect = self._overlay.last_selection_rect()
        if rect is None:
            screen = QGuiApplication.primaryScreen()
            rect = screen.availableGeometry() if screen else QRect(100, 100, 400, 300)
        self._toolbar.show_near(rect)
        self._toast.info(UI_TOAST_SCROLL_DONE)
        _LOG.info("长截图完成：%dx%d，等待去向动作", image.width(), image.height())

    def _on_scroll_cancelled(self) -> None:
        if self._scroll is not None:
            self._scroll.deleteLater()
            self._scroll = None
        self._shot = None
        _LOG.info("长截图已取消，本轮结束")

    # ---- 动作：发博客（P0） ----
    def on_publish(self) -> None:
        self._toolbar.hide()
        shot = self._shot
        if shot is None:
            return
        self._toast.info(UI_TOAST_UPLOADING)
        filename = f"screenshot-{datetime.now().strftime(TIMESTAMP_FORMAT)}.png"
        threading.Thread(target=self._publish_worker, args=(shot, filename), daemon=True).start()

    def _publish_worker(self, shot: QImage, filename: str) -> None:
        """后台线程：编码 PNG → ensure_token → 上传。结果经信号回主线程。"""
        try:
            png = self._encode_png(shot)
            data = self._api.upload_public_image(png, filename)
        except ToolError as exc:
            _LOG.error("发布失败：code=%s msg=%s", exc.code, exc.message)
            self._publish_failed.emit(exc.message, exc.code)
            return
        except OSError:
            _LOG.error("PNG 编码失败", exc_info=True)
            self._publish_failed.emit(UI_TOAST_PNG_ENCODE_FAILED, "png")
            return
        _LOG.info("发布成功：%s", data.get("url", ""))
        self._publish_ok.emit(str(data.get("markdown", "")))

    def _on_publish_ok(self, markdown: str) -> None:
        self._shot = None
        if markdown and self._clipboard.copy_text(markdown):
            self._toast.success(UI_TOAST_COPY_OK)
        else:
            self._toast.error(UI_TOAST_PNG_ENCODE_FAILED if not markdown else "复制到剪贴板失败")

    def _on_publish_failed(self, message: str, code: str) -> None:
        if code == "auth":
            # Bug2：未登录时只发托盘气泡用户感知不到 → 除气泡外直接弹设置
            self._on_publish_auth_failed()
            return
        self.fallback_save_local(message)

    def _on_publish_auth_failed(self) -> None:
        """未登录：气泡改引导性文案并延长展示，同时打开设置聚焦账号输入框。

        截图仍先回退存本地避免丢失；用户登录后可重新截图发布。
        """
        shot = self._shot
        self._shot = None
        path: str | None = None
        if shot is not None:
            try:
                path = self._saver.save(shot)
                _LOG.info("未登录回退存本地：%s", path)
            except OSError:
                _LOG.error("未登录回退存本地失败", exc_info=True)
        if path:
            self._toast.error(
                UI_TOAST_FALLBACK_AUTH.format(path=path), timeout_ms=UI_TOAST_AUTH_TIMEOUT_MS
            )
        else:
            self._toast.error(UI_TOAST_AUTH_GUIDE, timeout_ms=UI_TOAST_AUTH_TIMEOUT_MS)
        self.open_settings(focus_account=True)

    # ---- 动作：存本地（P0） ----
    def on_save_local(self) -> None:
        self._toolbar.hide()
        shot = self._shot
        if shot is None:
            return
        self._shot = None
        try:
            path = self._saver.save(shot)
            self._toast.success(UI_TOAST_SAVED.format(path=path))
            _LOG.info("已存本地：%s", path)
        except OSError as exc:
            self._toast.error(UI_TOAST_SAVE_FAILED.format(reason=exc))
            _LOG.error("存本地失败", exc_info=True)

    # ---- 动作：OCR 交接（P1） ----
    def on_ocr_handoff(self) -> None:
        self._toolbar.hide()
        shot = self._shot
        if shot is None:
            return
        try:
            png = self._encode_png(shot)
        except OSError:
            self._toast.error(UI_TOAST_PNG_ENCODE_FAILED)
            _LOG.error("PNG 编码失败", exc_info=True)
            return
        if len(png) > HANDOFF_MAX_BYTES:
            # 对齐前端 MAX_TOTAL_BYTES 上限；保留截图供用户改走存本地
            self._toast.error("截图过大（>20MB），无法交接 OCR，请改用存本地")
            _LOG.warning("OCR 交接放弃：PNG %d 字节超限", len(png))
            return
        try:
            endpoint = self._handoff.serve(png)
        except OSError:
            self._toast.error("本地交接端点启动失败")
            _LOG.error("交接端点启动失败", exc_info=True)
            return
        deep_link = f"{self._config.blog_frontend_base}/blog#screenshot-handoff={endpoint}"
        self._handoff.open_blog_with_token(deep_link)
        self._shot = None
        self._toast.info(UI_TOAST_OCR_OPENED)

    # ---- 失败回退（P0 验收硬性要求） ----
    def fallback_save_local(self, reason: str) -> None:
        """上传失败 → 存本地 + 气泡提示，结束本轮。"""
        shot = self._shot
        self._shot = None
        if shot is None:
            return
        try:
            path = self._saver.save(shot)
            self._toast.error(UI_TOAST_FALLBACK.format(reason=reason, path=path))
            _LOG.info("回退存本地：%s", path)
        except OSError as exc:
            self._toast.error(UI_TOAST_SAVE_FAILED.format(reason=exc))
            _LOG.error("回退存本地也失败", exc_info=True)

    # ---- 设置与自启 ----
    def open_settings(self, focus_account: bool = False) -> None:
        """打开设置对话框；确认后热键即时生效、凭据落盘、自启写注册表。

        focus_account=True（未登录引导）：弹窗后聚焦账号输入框。
        """
        dialog = SettingsDialog(self._config, self._credentials)
        if focus_account:
            dialog.focus_account()
        if dialog.exec() != SettingsDialog.DialogCode.Accepted.value:
            return
        values = dialog.values()
        self._config.save({
            "hotkey": values["hotkey"],
            "backend_base": values["backend_base"],
            "blog_frontend_base": values["blog_frontend_base"],
            "save_dir": values["save_dir"],
            "autostart": values["autostart"],
        })
        if values["password"]:
            self._credentials.save_login(values["username"], values["password"])
            _LOG.info("登录凭据已更新（DPAPI 落盘）")
        hotkey = self._config.hotkey
        if self._hotkey.register(hotkey, self.on_hotkey):
            self._tray.update_hotkey_hint(hotkey)
        else:
            self._tray.update_hotkey_hint(f"{hotkey}（注册失败）")
            self._toast.error(UI_TOAST_HOTKEY_FAILED.format(hotkey=hotkey))
        self._set_autostart(values["autostart"])
        self._tray.set_autostart_checked(values["autostart"])
        self._toast.success(UI_TOAST_SETTINGS_SAVED)

    def _on_autostart_toggled(self, enabled: bool) -> None:
        self._set_autostart(enabled)

    def _set_autostart(self, enabled: bool) -> None:
        """写/删 HKCU Run 键（docs/system_design.md T05）。"""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, self._autostart_command())
                    _LOG.info("开机自启已写入：%s", self._autostart_command())
                else:
                    try:
                        winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
                        _LOG.info("开机自启已移除")
                    except FileNotFoundError:
                        pass
        except OSError:
            self._toast.error("开机自启设置失败（注册表写入被拒绝）")
            _LOG.error("写 HKCU Run 失败", exc_info=True)

    @staticmethod
    def _autostart_command() -> str:
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe") if exe.name == "python.exe" else exe
        script = Path(__file__).resolve().parent.parent / "main.py"
        return f'"{pythonw}" "{script}"'

    # ---- 工具 ----
    @staticmethod
    def _encode_png(shot: QImage) -> bytes:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        ok = shot.save(buffer, "PNG")
        data = bytes(buffer.data())
        buffer.close()
        if not ok or not data:
            raise OSError("PNG 编码失败")
        return data
