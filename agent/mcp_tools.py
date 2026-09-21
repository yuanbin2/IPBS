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

    def _web_search(self, query: str) -> str:
        """Search the public web through DuckDuckGo's keyless JSON API.

        The endpoint is intentionally fixed instead of accepting a URL from the
        database, so an administrator cannot accidentally turn this tool into
        an SSRF proxy. Only the result title, URL and snippet are returned.
        """
        query = query.strip()
        if not query:
            return "网页搜索失败：query 不能为空。"

        provider = os.getenv("WEB_SEARCH_PROVIDER", "auto").strip().lower()
        if provider not in {"auto", "duckduckgo", "bing"}:
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
                else:
                    search_results, error = self._bing_html_search(search_query, limit=limit + 4, timeout=timeout)
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
                return f"网页搜索失败：外部搜索服务暂时不可用（{diagnostics}）。请检查服务器网络、代理或防火墙配置。"
            return "网页搜索没有返回可用结果。请换用更明确的关键词。"

        lines = [
            f"网页搜索结果（provider={used_provider}，原始问题={query}，检索式={' | '.join(search_queries)}，结果数={len(results)}）："
        ]
        for index, (text, target_url) in enumerate(results[:limit], start=1):
            lines.append(f"[{index}] {text}\n{target_url}")
        return "\n\n".join(lines)

    @staticmethod
    def _provider_order(provider: str) -> list[str]:
        if provider in {"auto", "duckduckgo"}:
            return ["duckduckgo", "bing"]
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
        cleaned = re.sub(
            r"^(please\s+)?(help\s+me\s+)?(use\s+)?(web|internet|online)?\s*(search|find|look\s+up)\s+",
            "",
            query.strip(),
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(请|请你|麻烦|帮我|请帮我|能否|可以)?\s*(用|使用)?\s*(网页|网络|网上|联网|互联网)?\s*(搜索|检索|查找|查询|查一下|搜一下)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" ，。？！,.!?:：")
        cleaned = re.sub(r"\s+", " ", cleaned) or query.strip()
        focused = re.sub(r"(请问|是什么|怎么样|有哪些|告诉我|介绍一下|相关信息)", " ", cleaned)
        focused = re.sub(r"\s+", " ", focused).strip(" ，。？！,.!?:：")
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
