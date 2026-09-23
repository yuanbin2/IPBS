"""搜索引擎 HTML 结果页解析器与 DuckDuckGo 跳转链接归一化。

三个解析器都把结果页 HTML 转成 ``[{"title", "url", "snippet"}]`` 字典列表；
只依赖标准库 ``html.parser``，不发起任何网络请求。
"""

from __future__ import annotations

import ipaddress
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            self._capture = "title"
            self._buffer = []
            self._href = attributes.get("href") or ""
        elif tag in {"a", "div"} and "result__snippet" in classes:
            self._capture = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "a":
            self.results.append({"title": " ".join(self._buffer).strip(), "url": self._href, "snippet": ""})
            self._capture = None
        elif self._capture == "snippet" and tag in {"a", "div"}:
            if self.results:
                self.results[-1]["snippet"] = " ".join(self._buffer).strip()
            self._capture = None


class _BingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._href = ""
        self._title = ""
        self._snippet = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "li" and "b_algo" in classes:
            self._in_result = True
            self._href = ""
            self._title = ""
            self._snippet = ""
        elif self._in_result and tag == "a" and not self._href:
            self._href = attributes.get("href") or ""
            self._capture = "title"
            self._buffer = []
        elif self._in_result and tag == "p":
            self._capture = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "a":
            self._title = " ".join(self._buffer).strip()
            self._capture = None
        elif self._capture == "snippet" and tag == "p":
            self._snippet = " ".join(self._buffer).strip()
            self._capture = None
        elif self._in_result and tag == "li":
            if self._title and self._href:
                self.results.append({"title": self._title, "url": self._href, "snippet": self._snippet})
            self._in_result = False


class _BaiduHTMLParser(HTMLParser):
    """Parse Baidu search result page HTML.

    Baidu wraps each result in a container div (class contains "result" or
    "c-container").  Inside, the first <a> whose parent is an <h3> carries the
    result title and target URL.  A sibling <span class="c-abstract"> or
    <div class="c-span-last"> holds the snippet.
    """

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._in_h3 = False
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._href = ""
        self._title = ""
        self._snippet = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        # Result container
        if tag == "div" and ("result" in classes or "c-container" in classes or "result-op" in classes):
            self._in_result = True
            self._in_h3 = False
            self._href = ""
            self._title = ""
            self._snippet = ""
        elif self._in_result and tag == "h3":
            self._in_h3 = True
        elif self._in_h3 and tag == "a" and not self._href:
            href = attributes.get("href") or ""
            if href and not href.startswith("#"):
                self._href = href
                self._capture = "title"
                self._buffer = []
        # Snippet area
        elif (
            self._in_result
            and tag in {"span", "div"}
            and ("c-abstract" in classes or "content-right_8Zs40" in classes or "c-span-last" in classes)
        ):
            self._capture = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "a":
            self._title = " ".join(self._buffer).strip()
            self._capture = None
        elif self._in_h3 and tag == "h3":
            self._in_h3 = False
        elif self._capture == "snippet" and tag in {"span", "div"}:
            self._snippet = " ".join(self._buffer).strip()
            self._capture = None
        # End of result container
        elif self._in_result and tag == "div" and not self._in_h3:
            if self._title and self._href:
                self.results.append({"title": self._title, "url": self._href, "snippet": self._snippet})
            self._in_result = False


def normalize_duckduckgo_url(raw_url: str) -> str:
    """解出 DuckDuckGo 跳转链接并拦截内网/非 HTTPS 目标（SSRF 防护）。"""
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    parsed = urlparse(raw_url)
    if parsed.netloc.endswith("duckduckgo.com"):
        redirected = parse_qs(parsed.query).get("uddg", [""])[0]
        raw_url = redirected or raw_url
        parsed = urlparse(raw_url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not hostname or hostname == "localhost" or hostname.endswith(".local"):
        return ""
    try:
        if ipaddress.ip_address(hostname).is_private:
            return ""
    except ValueError:
        pass
    return raw_url
