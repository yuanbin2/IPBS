"""博客 API 客户端：公开媒体 / 私有笔记图片上传（带 401 刷新重试与错误映射）。

接口出处（均已核对真实代码）：
- POST /api/agent/blog/images/（BlogImageUploadView，backend/apps/agent_api/views/blog_articles.py L194-286）
  multipart 字段 image，Bearer JWT，要求 OPERATOR 角色，≤5MB，201 {url, markdown}
- POST /api/agent/blog/notes/images/（PrivateNoteImageUploadView，blog_note_images.py L89-145）
  multipart 字段 image，Bearer JWT，≤5MiB，60 张/时，201 {id, url, requires_auth, ...}
- 后端错误响应统一 {"detail": str, "code": str}（views/common.py L108-110），
  code 为小写（backend/apps/agent_api/exceptions.py）。
"""
from __future__ import annotations

import logging

import requests

from app.constants import (
    CODE_FORBIDDEN,
    CODE_NOT_AUTHENTICATED,
    CODE_RATE_LIMITED,
    CODE_UPSTREAM_UNAVAILABLE,
    CODE_VALIDATION_ERROR,
    HTTP_TIMEOUT,
    MAX_UPLOAD_BYTES,
    MSG_BACKEND_DOWN,
    MSG_FORBIDDEN,
    MSG_IMAGE_TOO_LARGE,
    MSG_NO_BACKEND,
    MSG_NOT_LOGGED_IN,
    MSG_RATE_LIMITED,
    MSG_UPLOAD_FAILED,
    NOTE_IMAGE_PATH,
    PUBLIC_IMAGE_PATH,
)
from app.errors import AuthError, NetworkError, UploadError
from core.config_store import ConfigStore
from services.auth_client import AuthClient

_LOG = logging.getLogger("tray.api")


class BlogApiClient:
    """上传客户端。所有失败抛 ToolError 子类，message 为用户可读文案。"""

    def __init__(self, config: ConfigStore, auth: AuthClient) -> None:
        self._config = config
        self._auth = auth

    # ---- 对外接口（类图约定） ----
    def upload_public_image(self, png_bytes: bytes, filename: str) -> dict:
        """上传公开博客媒体，返回 {url, markdown}。markdown 可直接进剪贴板。"""
        return self._post_multipart(PUBLIC_IMAGE_PATH, png_bytes, filename)

    def upload_note_image(self, png_bytes: bytes, filename: str) -> dict:
        """上传私有笔记图片，返回 {id, url, requires_auth: True, ...}。"""
        return self._post_multipart(NOTE_IMAGE_PATH, png_bytes, filename)

    # ---- 内部 ----
    def _post_multipart(self, path: str, png_bytes: bytes, filename: str) -> dict:
        """带错误映射的 multipart 上传；401 时刷新 token 重试一次。"""
        if len(png_bytes) > MAX_UPLOAD_BYTES:
            # 本地预检：超限直接走回退，不做压缩（设计 §5.2）
            raise UploadError(CODE_VALIDATION_ERROR, MSG_IMAGE_TOO_LARGE)
        token = self._auth.ensure_token()
        url = self._config.backend_base + path
        for attempt in (1, 2):
            try:
                response = requests.post(
                    url,
                    files={"image": (filename, png_bytes, "image/png")},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=HTTP_TIMEOUT,
                )
            except requests.RequestException as exc:
                _LOG.error("上传请求失败：%s", url, exc_info=True)
                raise NetworkError(MSG_NO_BACKEND) from exc
            if response.status_code in (200, 201):
                data = response.json()
                _LOG.info("上传成功：%s → %s", path, data.get("url", ""))
                return data
            if response.status_code == 401 and attempt == 1:
                if self._auth.refresh_access() and self._auth.access_token:
                    token = self._auth.access_token
                    _LOG.info("token 已刷新，重试上传")
                    continue
                raise AuthError(MSG_NOT_LOGGED_IN)
            self._raise_for_response(response, path)
        raise AuthError(MSG_NOT_LOGGED_IN)  # 防御分支，理论不可达

    def _raise_for_response(self, response: requests.Response, path: str) -> None:
        """按 docs/system_design.md §7 错误码映射抛出 ToolError。"""
        code, detail = "", ""
        try:
            body = response.json()
            if isinstance(body, dict):
                code = str(body.get("code", ""))
                detail = str(body.get("detail", ""))
        except ValueError:
            pass
        _LOG.warning("上传失败：%s HTTP %s code=%s detail=%s", path, response.status_code, code, detail)
        if code == CODE_FORBIDDEN:
            raise UploadError(code, MSG_FORBIDDEN)
        if code == CODE_NOT_AUTHENTICATED:
            raise AuthError(MSG_NOT_LOGGED_IN)
        if code == CODE_VALIDATION_ERROR:
            raise UploadError(code, MSG_IMAGE_TOO_LARGE)
        if code == CODE_RATE_LIMITED:
            raise UploadError(code, MSG_RATE_LIMITED)
        if code == CODE_UPSTREAM_UNAVAILABLE or response.status_code >= 500:
            raise UploadError(CODE_UPSTREAM_UNAVAILABLE, MSG_BACKEND_DOWN)
        raise UploadError(code or "unknown", f"{MSG_UPLOAD_FAILED}（HTTP {response.status_code}）")
