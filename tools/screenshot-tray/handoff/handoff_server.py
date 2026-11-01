"""P1 OCR 交接服务（方案 C，docs/system_design.md §9）：

ThreadingHTTPServer 绑定 127.0.0.1 随机端口，`GET /s/<token>.png` 返回 PNG
（128bit 随机 token、5 分钟过期、TTL 内可重复取）。所有响应统一携带
Access-Control-Allow-Origin: *：博客页（5173/5174）fetch 本端点属于跨源，
缺失 CORS 头时浏览器会拦截响应体，前端表现为 "Failed to fetch"（实测根因）。
TTL 内可重复取是为前端传输失败后的重试兜底——原「取后即焚」会让重试必然 410；
安全性仍可控（仅绑 127.0.0.1 + 128bit 随机 token + 5 分钟 TTL）。
深链 fragment 只带 "screenshot-handoff=127.0.0.1:<port>/s/<token>" 引用，
前端（BlogView.vue 增量）fetch 端点后进入既有 ScreenshotOcrDialog 链路。
"""
from __future__ import annotations

import logging
import re
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.constants import HANDOFF_TOKEN_TTL_SECONDS

_LOG = logging.getLogger("tray.handoff")

_TOKEN_PATH_RE = re.compile(r"^/s/([0-9a-f]{32})\.png$")


class _HandoffHTTPServer(ThreadingHTTPServer):
    """持有截图载荷与校验逻辑的 HTTP 服务器（TTL 内可重复取）。"""

    daemon_threads = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.png_bytes: bytes | None = None
        self.token: str | None = None
        self.expires_at: float = 0.0

    def load(self, token: str, png_bytes: bytes) -> None:
        self.token = token
        self.png_bytes = png_bytes
        self.expires_at = time.monotonic() + HANDOFF_TOKEN_TTL_SECONDS

    def fetch(self, token: str | None) -> bytes | None:
        """校验 token 且未过期则返回 PNG（TTL 内可重复取，供前端失败重试）。

        token 不匹配或已过期均返回 None，调用方按 HTTP 状态区分：
        路径不合法→404；路径合法但 token 不符或已过期→410（过期时清空载荷）。
        """
        if token is None or token != self.token:
            return None
        if time.monotonic() > self.expires_at:
            self.png_bytes, self.token = None, None
            _LOG.info("交接 token 已过期，载荷已清理")
            return None
        _LOG.info("交接 token 校验通过（TTL 内可重复取）")
        return self.png_bytes


class _HandoffHandler(BaseHTTPRequestHandler):
    server_version = "BlogScreenshotHandoff/1.1"

    def do_GET(self) -> None:  # noqa: N802（BaseHTTPRequestHandler 固定命名）
        server: _HandoffHTTPServer = self.server  # type: ignore[assignment]
        match = _TOKEN_PATH_RE.match(self.path)
        png = server.fetch(match.group(1)) if match else None
        self.send_response(200 if png is not None else (404 if match is None else 410))
        # 跨源响应必须带 CORS 头，否则浏览器拦截响应体（前端报 Failed to fetch）
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        if png is None:
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png)))
        self.end_headers()
        self.wfile.write(png)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # 日志统一由工具 RotatingFileHandler 记录，HTTP 层静默
        _LOG.debug("handoff %s %s", format % args)


class HandoffServer:
    """临时本地端点 + 深链打开。非线程安全：serve/stop 须在主线程调用。"""

    def __init__(self) -> None:
        self._httpd: _HandoffHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def serve(self, png_bytes: bytes) -> str:
        """持有 PNG 并启动端点，返回 fragment 值 "127.0.0.1:<port>/s/<token>"。"""
        self.stop()
        token = secrets.token_hex(16)  # 32 位 hex，与前端校验正则一致
        self._httpd = _HandoffHTTPServer(("127.0.0.1", 0), _HandoffHandler)
        self._httpd.load(token, png_bytes)
        port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="handoff-server", daemon=True)
        self._thread.start()
        _LOG.info("交接端点已启动：127.0.0.1:%s/s/%s（%d 字节，%d 秒内可重复取）",
                  port, token, len(png_bytes), HANDOFF_TOKEN_TTL_SECONDS)
        return f"127.0.0.1:{port}/s/{token}"

    def open_blog_with_token(self, url: str) -> None:
        """用默认浏览器打开深链（如 http://127.0.0.1:5174/blog#screenshot-handoff=...）。"""
        _LOG.info("打开 OCR 深链：%s", url)
        webbrowser.open(url)

    def stop(self) -> None:
        """关闭旧端点线程（幂等）。"""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread = None
