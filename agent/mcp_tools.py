"""本地 MCP 风格工具适配器。

这里只实现具体工具调用；工具是否注册、是否启用以及是否需要审批，
由上层 MultiAgentSupervisor 和数据库中的 MCPTool 配置共同决定。
"""

from __future__ import annotations

import json
import ipaddress
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .tools import search_project_files


@dataclass(frozen=True)
class MCPToolExecution:
    name: str
    input: str
    output: str


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
        elif self._in_result and tag in {"span", "div"} and (
            "c-abstract" in classes or "content-right_8Zs40" in classes or "c-span-last" in classes
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


class LocalMCPToolRunner:
    """Small local MCP-style adapter layer with explicit tool names and scopes."""

    def __init__(self, project_root: Path):
        self.project_root = project_root

    def run(self, tool_name: str, query: str) -> MCPToolExecution:
        # 显式分派而不是动态 import/反射，可避免模型构造任意函数名执行。
        if tool_name == "local_file_search":
            return MCPToolExecution(tool_name, query, search_project_files(self.project_root, query))
        if tool_name == "git_repo_info":
            return MCPToolExecution(tool_name, query, self._git_repo_info())
        if tool_name == "safe_database_stats":
            return MCPToolExecution(tool_name, query, self._safe_database_stats())
        if tool_name == "web_search":
            return MCPToolExecution(tool_name, query, self._web_search(query))
        if tool_name == "current_time":
            return MCPToolExecution(tool_name, query, self._current_time())
        return MCPToolExecution(tool_name, query, f"未知 MCP 工具：{tool_name}")

    def _git_repo_info(self) -> str:
        commands = [
            ("branch", ["git", "branch", "--show-current"]),
            ("latest_commit", ["git", "log", "-1", "--oneline"]),
            ("status", ["git", "status", "--short"]),
        ]
        lines: list[str] = []
        for label, command in commands:
            try:
                completed = subprocess.run(
                    command,
                    cwd=self.project_root,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                output = completed.stdout.strip() or completed.stderr.strip() or "-"
            except Exception as exc:
                output = f"unavailable: {exc}"
            lines.append(f"{label}: {output}")
        return "\n".join(lines)

    def _safe_database_stats(self) -> str:
        from apps.agent_api.models import BlogArticle, Conversation, Document, KnowledgeBase, MCPTool

        stats = {
            "knowledge_bases": KnowledgeBase.objects.count(),
            "documents": Document.objects.count(),
            "published_articles": BlogArticle.objects.filter(status=BlogArticle.Status.PUBLISHED).count(),
            "conversations": Conversation.objects.count(),
            "registered_mcp_tools": MCPTool.objects.count(),
            "enabled_mcp_tools": MCPTool.objects.filter(is_enabled=True).count(),
        }
        return "\n".join(f"- {key}: {value}" for key, value in stats.items())

    @staticmethod
    def _current_time() -> str:
        timezone_name = os.getenv("APP_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai"
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            timezone_name = "UTC"
            timezone = ZoneInfo("UTC")
        current = datetime.now(timezone)
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        return (
            f"现在是 {current:%Y年%m月%d日 %H:%M:%S} "
            f"{weekdays[current.weekday()]}（{timezone_name}，UTC{current:%z}）。"
        )

    def _try_weather_query(self, query: str) -> str | None:
        """Detect weather queries and use wttr.in for reliable, structured results.

        Returns a formatted weather string if the query is weather-related,
        or None to fall through to the general web search path.
        """
        weather_keywords = ["天气", "天气预报", "气温", "温度", "weather", "forecast", "下雨", "晴天", "阴天"]
        lowered = query.lower()
        if not any(kw in lowered for kw in weather_keywords):
            return None

        # Try to extract a city/location name from the query
        # Common patterns: "北京天气", "明天北京的天气", "上海天气预报"
        location_match = re.search(r"([一-鿿]{2,4})(?:的|市|省|区|县)?(?:天气|气温|温度)", query)
        location = location_match.group(1) if location_match else ""

        # Also try English city names
        if not location:
            en_match = re.search(r"(?:weather|forecast|temperature)\s+(?:in|for)\s+([A-Za-z\s]+)", query, re.IGNORECASE)
            location = en_match.group(1).strip() if en_match else ""

        # If no explicit location, use empty string (wttr.in will use IP geolocation)
        # This handles cases like "明天的天气预报" where no city is mentioned

        timeout = self._bounded_int(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "10"), default=10, minimum=2, maximum=30)

        # Try wttr.in - a free weather service that returns plain text
        # When location is empty, wttr.in uses IP geolocation
        try:
            location_path = location if location else ""
            url = f"https://wttr.in/{location_path}?format=j1&lang=zh"
            request = Request(url, headers={"User-Agent": "curl/7.68.0", "Accept": "application/json"})
            with self._open_url(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))

            current = data.get("current_condition", [{}])[0]
            forecasts = data.get("weather", [])

            location_label = location if location else "您的位置（IP定位）"
            lines = [f"🌤 {location_label}天气实况（数据来源：wttr.in）："]
            if current:
                temp = current.get("temp_C", "?")
                feels = current.get("FeelsLikeC", "?")
                humidity = current.get("humidity", "?")
                wind = current.get("windspeedKmph", "?")
                desc_cn = current.get("lang_zh", [{}])
                desc = desc_cn[0].get("value", "") if desc_cn else current.get("weatherDesc", [{}])[0].get("value", "")
                lines.append(f"  当前温度：{temp}°C（体感 {feels}°C）")
                lines.append(f"  天气状况：{desc}")
                lines.append(f"  湿度：{humidity}%，风速：{wind} km/h")

            if forecasts:
                lines.append(f"\n📅 未来天气预报：")
                for day in forecasts[:3]:
                    date = day.get("date", "")
                    max_temp = day.get("maxtempC", "?")
                    min_temp = day.get("mintempC", "?")
                    hourly = day.get("hourly", [])
                    day_desc = ""
                    if hourly:
                        noon = hourly[4] if len(hourly) > 4 else hourly[0]
                        desc_cn = noon.get("lang_zh", [{}])
                        day_desc = desc_cn[0].get("value", "") if desc_cn else noon.get("weatherDesc", [{}])[0].get("value", "")
                    lines.append(f"  {date}：{min_temp}°C ~ {max_temp}°C，{day_desc}")

            return "\n".join(lines)
        except Exception:
            pass

        # Fallback: search Chinese weather sites directly
        try:
            search_url = "https://www.baidu.com/s?" + urlencode({"wd": f"{location} 天气预报 明日"})
            request = Request(search_url, headers={
                "Accept": "text/html",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
            with self._open_url(request, timeout=timeout) as response:
                html = response.read().decode("utf-8", errors="replace")
            # Extract weather data from Baidu's inline weather widget (if present)
            # Baidu embeds weather in a <div class="op_weather4_t498"> or similar
            temp_match = re.search(r'(\-?\d+)\s*°', html)
            if temp_match:
                return f"🌤 {location}天气：从百度搜索结果获取到温度 {temp_match.group(1)}°C（建议访问 weather.com.cn 获取详细预报）"
        except Exception:
            pass

        return None

    def _web_search(self, query: str) -> str:
        """Search the public web through DuckDuckGo's keyless JSON API.

        The endpoint is intentionally fixed instead of accepting a URL from the
        database, so an administrator cannot accidentally turn this tool into
        an SSRF proxy. Only the result title, URL and snippet are returned.
        """
        query = query.strip()
        if not query:
            return "网页搜索失败：query 不能为空。"

        # For weather queries, use wttr.in directly for reliable results
        weather_result = self._try_weather_query(query)
        if weather_result:
            return weather_result

        provider = os.getenv("WEB_SEARCH_PROVIDER", "auto").strip().lower()
        if provider not in {"auto", "duckduckgo", "bing", "baidu"}:
            return f"网页搜索配置错误：不支持 provider={provider}。"

        limit = self._bounded_int(os.getenv("WEB_SEARCH_MAX_RESULTS", "8"), default=8, minimum=3, maximum=12)
        timeout = self._bounded_int(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "10"), default=10, minimum=2, maximum=30)
        results: list[tuple[str, str]] = []
        errors: list[str] = []
        search_queries = self._build_search_queries(query)
        used_provider = provider
        for candidate_provider in self._provider_order(provider):
            provider_results: list[tuple[str, str]] = []
            for search_query in search_queries:
                if candidate_provider == "duckduckgo":
                    search_results, error = self._duckduckgo_html_search(search_query, limit=limit + 4, timeout=timeout)
                elif candidate_provider == "bing":
                    search_results, error = self._bing_html_search(search_query, limit=limit + 4, timeout=timeout)
                else:
                    search_results, error = self._baidu_html_search(search_query, limit=limit + 4, timeout=timeout)
                provider_results.extend(search_results)
                if error:
                    errors.append(error)
            provider_results = self._deduplicate_and_rerank(search_queries[0], provider_results, limit=limit)
            if not provider_results and candidate_provider == "duckduckgo":
                provider_results, error = self._duckduckgo_instant_answer(
                    search_queries[0],
                    limit=limit,
                    timeout=timeout,
                )
                if error:
                    errors.append(error)
            if provider_results:
                results = provider_results
                used_provider = candidate_provider
                break
        if not results:
            if errors:
                diagnostics = "；".join(dict.fromkeys(errors))
                return (
                    f"网页搜索失败：所有搜索服务均不可用（{diagnostics}）。\n\n"
                    "可能的原因：\n"
                    "1. 服务器无法访问外部网络（DuckDuckGo/Bing 在中国大陆被墙）\n"
                    "2. 未配置代理（可在环境变量 WEB_SEARCH_PROXY 中设置 HTTP 代理）\n"
                    "3. 百度搜索页面结构变更导致解析失败\n\n"
                    "建议：\n"
                    "- 在 .env 中设置 WEB_SEARCH_PROXY=http://127.0.0.1:7890（你的代理地址）\n"
                    "- 或设置 WEB_SEARCH_PROVIDER=baidu 优先使用百度搜索"
                )
            return "网页搜索没有返回可用结果。请换用更明确的关键词。"

        lines = [
            f"网页搜索结果（provider={used_provider}，原始问题={query}，检索式={' | '.join(search_queries)}，结果数={len(results)}）："
        ]
        for index, (text, target_url) in enumerate(results[:limit], start=1):
            lines.append(f"[{index}] {text}\n{target_url}")
        return "\n\n".join(lines)

    @staticmethod
    def _provider_order(provider: str) -> list[str]:
        # Auto mode tries Baidu first (accessible in mainland China),
        # then falls back to DuckDuckGo and Bing (may require proxy).
        if provider == "auto":
            return ["baidu", "duckduckgo", "bing"]
        if provider == "duckduckgo":
            return ["duckduckgo", "bing", "baidu"]
        if provider == "bing":
            return ["bing", "baidu"]
        if provider == "baidu":
            return ["baidu"]
        return [provider]

    def _duckduckgo_instant_answer(self, query: str, *, limit: int, timeout: int) -> tuple[list[tuple[str, str]], str]:
        url = "https://api.duckduckgo.com/?" + urlencode(
            {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        )
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "KnowledgeAgent/1.0"})
        try:
            with self._open_url(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            return [], self._network_error_message("DuckDuckGo instant answer", exc)

        results: list[tuple[str, str]] = []
        if payload.get("AbstractText") and payload.get("AbstractURL"):
            results.append((str(payload["AbstractText"]), str(payload["AbstractURL"])))
        for item in payload.get("RelatedTopics", []):
            candidates = item.get("Topics", []) if isinstance(item, dict) and "Topics" in item else [item]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                text = str(candidate.get("Text", "")).strip()
                target_url = self._normalize_duckduckgo_url(str(candidate.get("FirstURL", "")).strip())
                if text and target_url:
                    results.append((text, target_url))
                if len(results) >= limit:
                    return results, ""
        return results, ""

    @staticmethod
    def _build_search_queries(query: str) -> list[str]:
        # Strip English search prefixes
        cleaned = re.sub(
            r"^(please\s+)?(help\s+me\s+)?(use\s+)?(web|internet|online)?\s*(search|find|look\s+up)\s+",
            "",
            query.strip(),
            flags=re.IGNORECASE,
        )
        # Strip Chinese search prefixes - comprehensive pattern that handles:
        # - Politeness: 请/帮我/能否/可以
        # - Tool/method: 用/使用 + 网页/网络/网上/联网/互联网
        # - "在...中" pattern: 在网络中/在网上
        # - Action verbs: 搜索/检索/查找/查询/搜/查/找
        # - Suffixes: 一下/看看/查查
        cleaned = re.sub(
            r"^(请|请你|麻烦|帮我|请帮我|能否|可以)?\s*"
            r"(用|使用)?\s*"
            r"(在?\s*(网页|网络|网上|联网|互联网)\s*中?\s*)?"
            r"(搜索|检索|查找|查询|搜|查|找)\s*(一下|看看|查查)?",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" ，。？！,.!?:：")
        cleaned = re.sub(r"\s+", " ", cleaned) or query.strip()
        focused = re.sub(r"(请问|是什么|怎么样|有哪些|告诉我|介绍一下|相关信息)", " ", cleaned)
        focused = re.sub(r"\s+", " ", focused).strip(" ，。？！,.!?:：")

        # For weather queries, add specific site targeting for better results
        weather_keywords = ["天气", "天气预报", "气温", "温度", "weather"]
        is_weather = any(kw in cleaned.lower() for kw in weather_keywords)
        if is_weather:
            # Try to extract location from the query
            location_match = re.search(r"([一-鿿]{2,4})(?:的|市|省|区|县)?(?:天气|气温|温度)", cleaned)
            location = location_match.group(1) if location_match else ""
            if location:
                focused = f"{location} 明日天气预报 详细"
            else:
                focused = f"{cleaned} site:weather.com.cn OR site:tianqi.com"

        queries = [focused or cleaned]
        if cleaned != queries[0] and len(cleaned) <= 100:
            queries.append(cleaned)
        return list(dict.fromkeys(queries))[:2]

    def _deduplicate_and_rerank(
        self,
        query: str,
        results: list[tuple[str, str]],
        *,
        limit: int,
    ) -> list[tuple[str, str]]:
        unique: dict[str, tuple[str, str, int]] = {}
        for position, (text, target_url) in enumerate(results):
            normalized_url = target_url.rstrip("/")
            if not normalized_url or normalized_url in unique:
                continue
            unique[normalized_url] = (text, target_url, position)

        ranked = sorted(
            unique.values(),
            key=lambda item: self._web_result_score(query, item[0], item[1], item[2]),
            reverse=True,
        )
        return [(text, target_url) for text, target_url, _ in ranked[:limit]]

    @staticmethod
    def _web_result_score(query: str, text: str, target_url: str, position: int) -> float:
        query_lower = query.lower()
        haystack = f"{text} {target_url}".lower()
        ascii_terms = re.findall(r"[a-z0-9][a-z0-9.+#_-]{1,}", query_lower)
        chinese_segments = re.findall(r"[\u4e00-\u9fff]{2,}", query_lower)
        chinese_terms = [segment for value in chinese_segments for segment in ([value] + [value[i:i + 2] for i in range(len(value) - 1)])]
        terms = list(dict.fromkeys([*ascii_terms, *chinese_terms]))
        overlap = sum(1 for term in terms if term in haystack)
        score = overlap * 3.0 - position * 0.08
        hostname = (urlparse(target_url).hostname or "").lower()
        if any(marker in query_lower for marker in ["官方", "官网", "official", "文档", "documentation"]):
            if hostname.endswith(".org"):
                score += 15.0
            elif hostname.startswith("docs.") or hostname.startswith("developer."):
                score += 4.0
            elif "readthedocs" in hostname:
                score -= 1.0
            stopwords = {"official", "documentation", "docs", "web", "search", "please", "framework"}
            core_terms = [term for term in ascii_terms if term not in stopwords and len(term) >= 3]
            compact_hostname = re.sub(r"[^a-z0-9]", "", hostname)
            score += sum(2.0 for term in core_terms if re.sub(r"[^a-z0-9]", "", term) in compact_hostname)
        if "github.com" in hostname and "github" in query_lower:
            score += 3.0
        return score

    def _duckduckgo_html_search(self, query: str, *, limit: int, timeout: int) -> tuple[list[tuple[str, str]], str]:
        request = Request(
            "https://html.duckduckgo.com/html/",
            data=urlencode({"q": query}).encode("utf-8"),
            headers={
                "Accept": "text/html",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0 KnowledgeAgent/1.0",
            },
        )
        try:
            with self._open_url(request, timeout=timeout) as response:
                html = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return [], self._network_error_message("DuckDuckGo HTML", exc)

        parser = _DuckDuckGoHTMLParser()
        parser.feed(html)
        results: list[tuple[str, str]] = []
        for item in parser.results:
            target_url = self._normalize_duckduckgo_url(item["url"])
            if not target_url:
                continue
            description = item["title"]
            if item["snippet"]:
                description = f"{description} — {item['snippet']}"
            results.append((description, target_url))
            if len(results) >= limit:
                break
        return results, ""

    def _bing_html_search(self, query: str, *, limit: int, timeout: int) -> tuple[list[tuple[str, str]], str]:
        request = Request(
            "https://www.bing.com/search?" + urlencode({"q": query}),
            headers={
                "Accept": "text/html",
                "User-Agent": "Mozilla/5.0 KnowledgeAgent/1.0",
            },
        )
        try:
            with self._open_url(request, timeout=timeout) as response:
                html = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return [], self._network_error_message("Bing HTML", exc)

        parser = _BingHTMLParser()
        parser.feed(html)
        results: list[tuple[str, str]] = []
        for item in parser.results:
            target_url = self._normalize_duckduckgo_url(item["url"])
            if not target_url:
                continue
            description = item["title"]
            if item["snippet"]:
                description = f"{description} — {item['snippet']}"
            results.append((description, target_url))
            if len(results) >= limit:
                break
        return results, ""

    def _baidu_html_search(self, query: str, *, limit: int, timeout: int) -> tuple[list[tuple[str, str]], str]:
        """Search through Baidu for users in mainland China."""
        request = Request(
            "https://www.baidu.com/s?" + urlencode({"wd": query, "rn": limit + 4}),
            headers={
                "Accept": "text/html",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        )
        try:
            with self._open_url(request, timeout=timeout) as response:
                html = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return [], self._network_error_message("Baidu HTML", exc)

        parser = _BaiduHTMLParser()
        parser.feed(html)
        results: list[tuple[str, str]] = []
        for item in parser.results:
            target_url = item["url"]
            if not target_url or target_url.startswith("#"):
                continue
            description = item["title"]
            if item["snippet"]:
                description = f"{description} — {item['snippet']}"
            results.append((description, target_url))
            if len(results) >= limit:
                break
        return results, ""

    @staticmethod
    def _open_url(request: Request, *, timeout: int):
        proxy = os.getenv("WEB_SEARCH_PROXY", "").strip()
        if not proxy:
            return urlopen(request, timeout=timeout)
        opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}))
        return opener.open(request, timeout=timeout)

    @staticmethod
    def _network_error_message(provider: str, exc: Exception) -> str:
        if isinstance(exc, HTTPError):
            return f"{provider} HTTP {exc.code}"
        if isinstance(exc, URLError):
            reason = getattr(exc, "reason", exc)
            return f"{provider} 网络错误：{reason}"
        if isinstance(exc, TimeoutError):
            return f"{provider} 请求超时"
        return f"{provider} {type(exc).__name__}: {exc}"

    @staticmethod
    def _normalize_duckduckgo_url(raw_url: str) -> str:
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

    @staticmethod
    def _bounded_int(raw_value: str, *, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))
