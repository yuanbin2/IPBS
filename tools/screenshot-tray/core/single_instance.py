"""命名互斥锁：防止托盘工具双开（kernel32.CreateMutexW）。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """进程级单实例锁。acquire() 返回 False 表示已有实例在运行。"""

    def __init__(self, name: str = "BlogScreenshotTool.Singleton.Mutex") -> None:
        self._name = name
        self._handle: wintypes.HANDLE | None = None

    def acquire(self) -> bool:
        """尝试持有互斥锁；已存在实例时返回 False。"""
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._handle = kernel32.CreateMutexW(None, False, self._name)
        return ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def release(self) -> None:
        """释放并关闭互斥锁句柄。"""
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
