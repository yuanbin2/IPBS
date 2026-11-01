"""配置对话框：热键、后端/前端地址、保存目录、账号密码、开机自启。"""
from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config_store import ConfigStore
from core.credential_store import CredentialStore
from services.hotkey_manager import parse_hotkey

_LOG = logging.getLogger("tray.settings")


class SettingsDialog(QDialog):
    """设置窗口。确认时校验热键格式；密码留空表示不修改。"""

    def __init__(self, config: ConfigStore, credentials: CredentialStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._credentials = credentials
        self.setWindowTitle("截图工具设置")
        self.setMinimumWidth(440)

        form = QFormLayout()
        self._hotkey_edit = QKeySequenceEdit(config.hotkey)
        form.addRow("全局热键", self._hotkey_edit)
        self._backend_edit = QLineEdit(config.backend_base)
        form.addRow("后端地址", self._backend_edit)
        self._frontend_edit = QLineEdit(config.blog_frontend_base)
        form.addRow("博客前端地址", self._frontend_edit)

        save_dir_row = QHBoxLayout()
        self._save_dir_edit = QLineEdit(str(config.save_dir))
        save_dir_row.addWidget(self._save_dir_edit)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_save_dir)
        save_dir_row.addWidget(browse)
        form.addRow("保存目录", save_dir_row)

        login = credentials.load_login()
        self._username_edit = QLineEdit(login[0] if login else "")
        form.addRow("账号", self._username_edit)
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText("留空则不修改密码")
        form.addRow("密码", self._password_edit)

        self._autostart_check = QCheckBox("开机自动启动（写入 HKCU Run）")
        self._autostart_check.setChecked(config.autostart)
        form.addRow(self._autostart_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def focus_account(self) -> None:
        """聚焦并全选账号输入框（未登录引导场景由控制器调用）。"""
        self._username_edit.setFocus()
        self._username_edit.selectAll()

    def _browse_save_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择保存目录", self._save_dir_edit.text())
        if chosen:
            self._save_dir_edit.setText(chosen)

    def values(self) -> dict:
        """收集表单值（hotkey 已小写化）。"""
        return {
            "hotkey": self._hotkey_edit.keySequence().toString().lower(),
            "backend_base": self._backend_edit.text().strip().rstrip("/"),
            "blog_frontend_base": self._frontend_edit.text().strip().rstrip("/"),
            "save_dir": self._save_dir_edit.text().strip(),
            "username": self._username_edit.text().strip(),
            "password": self._password_edit.text(),
            "autostart": self._autostart_check.isChecked(),
        }

    def accept(self) -> None:  # noqa: D102
        values = self.values()
        if not values["backend_base"] or not values["save_dir"]:
            QMessageBox.warning(self, "配置无效", "后端地址与保存目录不能为空。")
            return
        try:
            parse_hotkey(values["hotkey"])
        except ValueError as exc:
            QMessageBox.warning(self, "热键无效", str(exc))
            return
        _LOG.info("设置确认：%s", {k: v for k, v in values.items() if k != "password"})
        super().accept()
