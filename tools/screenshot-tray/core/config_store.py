"""config.json 读写（%APPDATA%/BlogScreenshotTool/，UTF-8，缺字段用默认值）。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.constants import CONFIG_PATH, DEFAULT_CONFIG

_LOG = logging.getLogger("tray.config")


class ConfigStore:
    """配置存取。首次运行自动按默认值生成 config.json；损坏时回退默认值。"""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self._path = Path(path)
        self._data: dict = self._load_file()

    # ---- 对外接口 ----
    def load(self) -> dict:
        """返回当前配置的浅拷贝。"""
        return dict(self._data)

    def save(self, patch: dict) -> None:
        """合并 patch 并落盘。"""
        self._data.update(patch)
        self._write()

    # ---- 便捷属性 ----
    @property
    def backend_base(self) -> str:
        return str(self._data.get("backend_base", DEFAULT_CONFIG["backend_base"])).rstrip("/")

    @property
    def blog_frontend_base(self) -> str:
        return str(self._data.get("blog_frontend_base", DEFAULT_CONFIG["blog_frontend_base"])).rstrip("/")

    @property
    def hotkey(self) -> str:
        return str(self._data.get("hotkey", DEFAULT_CONFIG["hotkey"])).lower()

    @property
    def save_dir(self) -> Path:
        return Path(str(self._data.get("save_dir", DEFAULT_CONFIG["save_dir"])))

    @property
    def save_layout(self) -> str:
        return str(self._data.get("save_layout", DEFAULT_CONFIG["save_layout"]))

    @property
    def autostart(self) -> bool:
        return bool(self._data.get("autostart", DEFAULT_CONFIG["autostart"]))

    # ---- 内部 ----
    def _load_file(self) -> dict:
        data = dict(DEFAULT_CONFIG)
        if self._path.exists():
            try:
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (OSError, ValueError):
                _LOG.warning("配置文件损坏，使用默认配置", exc_info=True)
        else:
            self._write_file(data)
        return data

    def _write(self) -> None:
        self._write_file(self._data)

    def _write_file(self, data: dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            _LOG.error("配置写入失败：%s", self._path, exc_info=True)
