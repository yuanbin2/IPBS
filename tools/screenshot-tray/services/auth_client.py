"""认证客户端：login / refresh，token 内存态 + DPAPI 落盘。

接口出处（均已核对）：
- POST /api/agent/auth/login/  → {token, access, refresh, user, session}
  （backend/apps/agent_api/views/auth.py L31-72）
- POST /api/agent/auth/refresh/ → {access, ...}（simplejwt TokenRefreshView）
"""
from __future__ import annotations

import logging

import requests

from app.constants import (
    HTTP_TIMEOUT,
    LOGIN_PATH,
    MSG_INVALID_CREDENTIALS,
    MSG_NO_BACKEND,
    REFRESH_PATH,
)
from app.errors import AuthError, NetworkError
from core.config_store import ConfigStore
from core.credential_store import CredentialStore

_LOG = logging.getLogger("tray.auth")


class AuthClient:
    """维护内存态 JWT，负责登录、刷新与落盘。"""

    def __init__(self, config: ConfigStore, credentials: CredentialStore) -> None:
        self._config = config
        self._credentials = credentials
        self._access: str | None = None
        self._refresh: str | None = None

    # ---- 对外接口（类图约定） ----
    @property
    def access_token(self) -> str | None:
        return self._access

    def login(self, username: str, password: str) -> bool:
        """密码登录。成功落盘 token 并返回 True；凭据错误返回 False；
        网络失败抛 NetworkError。"""
        url = self._config.backend_base + LOGIN_PATH
        try:
            response = requests.post(url, json={"username": username, "password": password}, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            _LOG.error("登录请求失败：%s", url, exc_info=True)
            raise NetworkError(MSG_NO_BACKEND) from exc
        if response.status_code != 200:
            _LOG.warning("登录失败：HTTP %s %s", response.status_code, response.text[:200])
            return False
        data = response.json()
        self._access = str(data.get("access") or data.get("token") or "")
        self._refresh = str(data.get("refresh") or "")
        if not self._access:
            _LOG.error("登录响应缺少 access token")
            return False
        self._credentials.save_tokens(self._access, self._refresh)
        _LOG.info("登录成功：%s", username)
        return True

    def ensure_token(self) -> str:
        """保证有可用 access token：内存 → DPAPI 落盘 token → 凭据自动登录。
        全部失败抛 AuthError（UI 提示未登录，可一键回退存本地）。"""
        if self._access:
            return self._access
        tokens = self._credentials.load_tokens()
        if tokens:
            self._access, self._refresh = tokens
            _LOG.info("从 DPAPI 恢复 token")
            return self._access
        login = self._credentials.load_login()
        if login and self.login(*login):
            return self._access  # type: ignore[return-value]  # login 成功后必非空
        _LOG.info("无可用登录态")
        raise AuthError("未登录或登录已过期，请在托盘设置中登录")

    def refresh_access(self) -> bool:
        """用 refresh token 续期；成功返回 True 并更新内存与落盘。"""
        if not self._refresh:
            return False
        url = self._config.backend_base + REFRESH_PATH
        try:
            response = requests.post(url, json={"refresh": self._refresh}, timeout=HTTP_TIMEOUT)
        except requests.RequestException:
            _LOG.error("刷新 token 请求失败：%s", url, exc_info=True)
            return False
        if response.status_code != 200:
            _LOG.warning("刷新 token 失败：HTTP %s", response.status_code)
            # refresh 已失效，清掉落盘 token，下次走密码自动登录
            self._refresh = None
            self._credentials.clear_tokens()
            return False
        access = str(response.json().get("access") or "")
        if not access:
            _LOG.error("刷新响应缺少 access token")
            return False
        self._access = access
        self._credentials.save_tokens(self._access, self._refresh or "")
        _LOG.info("token 刷新成功")
        return True

    def invalidate(self) -> None:
        """丢弃内存态（保留落盘凭据，供下次自动登录）。"""
        self._access = None

    @property
    def invalid_credentials_message(self) -> str:
        return MSG_INVALID_CREDENTIALS
