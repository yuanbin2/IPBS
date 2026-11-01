"""Fetch a public image for an explicit HTML import, with a pinned public IP.

This does not follow redirects, forward browser cookies, or allow the HTTP
client to perform a second DNS lookup after the address has been checked.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
import uuid
import warnings
from io import BytesIO
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

from .blog_media import MAX_IMAGE_BYTES, validate_blog_image

MAX_REMOTE_IMAGE_URL_LENGTH = 2048
REMOTE_IMAGE_TIMEOUT_SECONDS = 5
REMOTE_IMAGE_READ_DEADLINE_SECONDS = 12
_CONTENT_TYPES = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "GIF": ("image/gif", ".gif"),
    "WEBP": ("image/webp", ".webp"),
}


class RemoteImageError(ValueError):
    def __init__(self, detail: str, *, http_status: int = 422):
        super().__init__(detail)
        self.http_status = http_status


def _public_address(host: str, port: int) -> str:
    try:
        # Literal IPs are unnecessary for normal web images and make internal
        # network targeting harder to audit. Only public DNS names are allowed.
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise RemoteImageError("图片来源必须是公开域名", http_status=400)
    if "." not in host or host.endswith((".local", ".internal", ".localhost")):
        raise RemoteImageError("图片来源必须是公开域名", http_status=400)
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError) as exc:
        raise RemoteImageError("图片域名无法解析") from exc
    if not addresses:
        raise RemoteImageError("图片域名无法解析")
    ips = [item[4][0] for item in addresses]
    try:
        parsed_ips = [ipaddress.ip_address(ip) for ip in ips]
    except ValueError as exc:
        raise RemoteImageError("图片域名解析结果无效", http_status=400) from exc
    if any(not ip.is_global for ip in parsed_ips):
        raise RemoteImageError("图片来源解析到了非公开网络地址", http_status=400)
    return ips[0]


def _request_pinned(host: str, port: int, ip: str, *, secure: bool, path: str):
    if secure:
        connection = http.client.HTTPSConnection(
            host, port, timeout=REMOTE_IMAGE_TIMEOUT_SECONDS, context=ssl.create_default_context()
        )
    else:
        connection = http.client.HTTPConnection(host, port, timeout=REMOTE_IMAGE_TIMEOUT_SECONDS)

    def connect_checked(_address, timeout=REMOTE_IMAGE_TIMEOUT_SECONDS, source_address=None):
        return socket.create_connection((ip, port), timeout=timeout)

    # HTTPSConnection wraps this socket with SNI and certificate verification
    # against the original hostname, while connecting only to the checked IP.
    connection._create_connection = connect_checked
    connection.request(
        "GET",
        path,
        headers={
            "Accept": "image/png,image/jpeg,image/gif,image/webp",
            "Accept-Encoding": "identity",
            "User-Agent": "BlogHtmlImport/2.4",
        },
    )
    return connection


def fetch_remote_image(raw_url: str) -> tuple[bytes, str]:
    if not raw_url or len(raw_url) > MAX_REMOTE_IMAGE_URL_LENGTH or any(ord(char) < 32 for char in raw_url):
        raise RemoteImageError("图片地址无效", http_status=400)
    try:
        parts = urlsplit(raw_url)
        host = (parts.hostname or "").encode("idna").decode("ascii").rstrip(".").lower()
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except (ValueError, UnicodeError) as exc:
        raise RemoteImageError("图片地址无效", http_status=400) from exc
    if (
        parts.scheme not in {"http", "https"}
        or not host
        or parts.username
        or parts.password
        or port != (443 if parts.scheme == "https" else 80)
        or any(char.isspace() for char in host)
    ):
        raise RemoteImageError("只允许公开域名的标准 HTTP/HTTPS 图片地址", http_status=400)
    ip = _public_address(host, port)
    path = parts.path or "/"
    if parts.query:
        path += f"?{parts.query}"
    connection = None
    try:
        connection = _request_pinned(host, port, ip, secure=parts.scheme == "https", path=path)
        response = connection.getresponse()
        if response.status != 200:
            raise RemoteImageError("原网站未返回可下载的图片，请选择本地图片文件")
        declared_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        if declared_type not in {item[0] for item in _CONTENT_TYPES.values()}:
            raise RemoteImageError("原网站返回的不是受支持的图片格式")
        length = response.getheader("Content-Length", "") or ""
        if length.isdigit() and int(length) > MAX_IMAGE_BYTES:
            raise RemoteImageError("原图片超过 5 MiB", http_status=413)
        expected_length = int(length) if length.isdigit() else None
        deadline = time.monotonic() + REMOTE_IMAGE_READ_DEADLINE_SECONDS
        chunks = []
        size = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RemoteImageError("图片下载超时，请选择本地图片文件")
            # http.client may detach its socket after response headers with
            # Connection: close; the response still owns a timed file handle.
            if connection.sock is not None:
                connection.sock.settimeout(min(REMOTE_IMAGE_TIMEOUT_SECONDS, remaining))
            chunk = response.read(min(64 * 1024, MAX_IMAGE_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                raise RemoteImageError("原图片超过 5 MiB", http_status=413)
            chunks.append(chunk)
            if expected_length is not None and size >= expected_length:
                break
        data = b"".join(chunks)
        if expected_length is not None and len(data) != expected_length:
            raise RemoteImageError("原图片下载不完整，请选择本地图片文件")
    except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as exc:
        raise RemoteImageError("图片下载失败，请选择本地图片文件") from exc
    finally:
        if connection is not None:
            connection.close()
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise RemoteImageError("原图片为空或超过 5 MiB", http_status=413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                detected = _CONTENT_TYPES.get(image.format)
            if not detected or declared_type != detected[0]:
                raise RemoteImageError("图片类型与文件内容不符")
            suffix = detected[1]
            validate_blog_image(BytesIO(data), f"{uuid.uuid4().hex}{suffix}", decode_frames=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning) as exc:
        if isinstance(exc, RemoteImageError):
            raise
        raise RemoteImageError("原网站返回的图片文件无效") from exc
    return data, suffix
