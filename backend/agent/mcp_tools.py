"""本地 MCP 风格工具适配器。

这里只实现具体工具调用；工具是否注册、是否启用以及是否需要审批，
由上层 MultiAgentSupervisor 和数据库中的 MCPTool 配置共同决定。
网页搜索的完整实现（provider 降级、解析、排序）在 ``web_search`` 模块。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import web_search
from .tools import search_project_files


@dataclass(frozen=True)
class MCPToolExecution:
    name: str
    input: str
    output: str


class LocalMCPToolRunner:
    """Small local MCP-style adapter layer with explicit tool names and scopes."""

    def __init__(self, project_root: Path, *, workspace_key: str | None = None):
        self.project_root = project_root
        self.workspace_key = workspace_key

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

        if self.workspace_key is None:
            return "workspace context required"
        scope = {"workspace_key": self.workspace_key}
        stats = {
            "knowledge_bases": KnowledgeBase.objects.filter(**scope).count(),
            "documents": Document.objects.filter(**scope).count(),
            "published_articles": BlogArticle.objects.filter(**scope, status=BlogArticle.Status.PUBLISHED).count(),
            "conversations": Conversation.objects.filter(**scope).count(),
            "registered_mcp_tools": MCPTool.objects.filter(**scope).count(),
            "enabled_mcp_tools": MCPTool.objects.filter(**scope, is_enabled=True).count(),
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
        return web_search.web_search(query)

    # 以下委托保留既有调用/测试入口，实现已移至 web_search 模块。
    @staticmethod
    def _build_search_queries(query: str) -> list[str]:
        return web_search.build_search_queries(query)

    def _deduplicate_and_rerank(
        self,
        query: str,
        results: list[tuple[str, str]],
        *,
        limit: int,
    ) -> list[tuple[str, str]]:
        return web_search.deduplicate_and_rerank(query, results, limit=limit)

    @staticmethod
    def _normalize_duckduckgo_url(raw_url: str) -> str:
        return web_search.normalize_duckduckgo_url(raw_url)
