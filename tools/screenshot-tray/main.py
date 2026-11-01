"""托盘截图工具入口：单实例锁 → DPI 声明 → 装配 AppController → 主循环。"""
from __future__ import annotations

import ctypes
import logging
import sys

from app.constants import APP_NAME
from core.log_manager import setup_logging
from core.single_instance import SingleInstance

_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


def _declare_dpi_awareness() -> None:
    """进程级 per-monitor DPI aware（V2 优先，失败回退 Win8.1 方案，再失败交给 Qt 默认）。"""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


def main() -> int:
    lock = SingleInstance()
    if not lock.acquire():
        # 已有实例在运行：静默退出（第二实例）
        return 0
    # DPI 声明必须在 QApplication 构造之前
    _declare_dpi_awareness()
    from PyQt6.QtWidgets import QApplication  # noqa: PLC0415  # 延迟导入：保证 DPI 声明先行

    from app.controller import AppController  # noqa: PLC0415

    setup_logging()
    log = logging.getLogger("tray.main")
    log.info("启动，argv=%s", sys.argv)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    try:
        controller = AppController(app)
        controller.start()
    except Exception:
        log.exception("启动失败")
        return 1
    code = -1
    try:
        code = app.exec()
    finally:
        lock.release()
        log.info("退出，code=%s", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
