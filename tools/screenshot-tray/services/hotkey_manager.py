"""全局热键：ctypes RegisterHotKey + QAbstractNativeEventFilter 收 WM_HOTKEY。

不使用 keyboard 库（低层钩子在管理员窗口/安全桌面失效且有杀软误报风险），
与 docs/system_design.md §1.1 的硬性要求一致。
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, pyqtSignal

_LOG = logging.getLogger("tray.hotkey")

WM_HOTKEY = 0x0312
HOTKEY_ID = 0xB10C  # 任意非零应用自定义 id

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

_MOD_MAP = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "meta": MOD_WIN,
}

# 字母/数字 VK 码与 ASCII 一致，标点与功能键单独映射
_PUNCT_VK = {
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
    "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}

_NAMED_VK = {
    **{f"f{i}": 0x70 + i - 1 for i in range(1, 13)},
    "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "tab": 0x09,
    "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22,
    "insert": 0x2D, "delete": 0x2E, "backspace": 0x08,
    "print": 0x2C, "prtsc": 0x2C, "snapshot": 0x2C,
}


def parse_hotkey(text: str) -> tuple[int, int]:
    """把 "ctrl+alt+a" 解析为 (modifiers, virtual_key)。非法输入抛 ValueError。"""
    parts = [part.strip().lower() for part in str(text).split("+") if part.strip()]
    if not parts:
        raise ValueError("热键为空")
    mods = 0
    key: str | None = None
    for part in parts:
        if part in _MOD_MAP:
            mods |= _MOD_MAP[part]
        elif key is None:
            key = part
        else:
            raise ValueError(f"热键包含多个主键：{text}")
    if key is None:
        raise ValueError(f"热键缺少主键：{text}")
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        vk = _PUNCT_VK.get(key) or _NAMED_VK.get(key)
    if vk is None:
        raise ValueError(f"不支持的主键：{key}")
    return mods, vk


class HotkeyNativeFilter(QAbstractNativeEventFilter):
    """Qt 原生事件过滤器：拦截 WM_HOTKEY 并回调。"""

    def __init__(self, hotkey_id: int, callback) -> None:
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, eventType, message):  # noqa: N802（PyQt 固定签名）
        if eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                self._callback()
        return False, 0


class HotkeyManager(QObject):
    """注册/注销全局热键；触发时发 triggered 信号（可传自定义回调）。"""

    triggered = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._filter: HotkeyNativeFilter | None = None
        self._registered = False

    def register(self, hotkey: str, on_fire=None) -> bool:
        """注册热键（先注销旧的）。成功返回 True；失败（被占用/格式非法）返回 False。"""
        self.unregister()
        try:
            mods, vk = parse_hotkey(hotkey)
        except ValueError as exc:
            _LOG.warning("热键解析失败：%s（%s）", hotkey, exc)
            return False
        if not self._user32.RegisterHotKey(None, HOTKEY_ID, mods, vk):
            _LOG.warning("RegisterHotKey 失败：%s（error=%s）", hotkey, ctypes.get_last_error())
            return False
        self._filter = HotkeyNativeFilter(HOTKEY_ID, on_fire or self.triggered.emit)
        QCoreApplication.instance().installNativeEventFilter(self._filter)
        self._registered = True
        _LOG.info("热键注册成功：%s", hotkey)
        return True

    def unregister(self) -> None:
        """注销热键并移除原生事件过滤器。"""
        if self._filter is not None:
            app = QCoreApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._filter)
            self._filter = None
        if self._registered:
            self._user32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False
            _LOG.info("热键已注销")
