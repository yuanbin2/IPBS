"""RotatingFileHandler 日志：%APPDATA%/BlogScreenshotTool/logs/tray.log，1MB × 3。

关键动作（热键、上传、回退）必打 INFO，异常必打含栈 ERROR。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.constants import LOG_DIR, LOG_FILE

_ROOT_LOGGER_NAME = "tray"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化工具根 logger（幂等），返回名为 ``tray`` 的 logger。"""
    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    if logger.handlers:
        return logger
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
