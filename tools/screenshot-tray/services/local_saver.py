"""存本地：按 {save_dir}/{yyyy}/{MM}/{yyyyMMdd-HHmmss}.png 布局保存 PNG。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtGui import QImage

from app.constants import TIMESTAMP_FORMAT


class LocalSaver:
    """本地保存器。布局模板来自配置 save_layout。"""

    def __init__(self, config) -> None:
        # config: core.config_store.ConfigStore（用鸭子类型以便离线自测替换桩）
        self._config = config

    def save(self, shot: QImage) -> Path:
        """保存 QImage 为 PNG，返回落盘路径；失败抛 OSError。"""
        path = self._dated_filename()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not shot.save(str(path), "PNG"):
            raise OSError(f"PNG 写入失败：{path}")
        return path

    def _dated_filename(self) -> Path:
        now = datetime.now()
        timestamp = now.strftime(TIMESTAMP_FORMAT)
        name = (
            self._config.save_layout
            .replace("{yyyy}", f"{now:%Y}")
            .replace("{MM}", f"{now:%m}")
            .replace("{yyyyMMdd-HHmmss}", timestamp)
        )
        return self._config.save_dir / name
