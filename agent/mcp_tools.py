from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .tools import search_project_files


@dataclass(frozen=True)
class MCPToolExecution:
    name: str
    input: str
    output: str


class LocalMCPToolRunner:
    """Small local MCP-style adapter layer with explicit tool names and scopes."""

    def __init__(self, project_root: Path):
        self.project_root = project_root

    def run(self, tool_name: str, query: str) -> MCPToolExecution:
        if tool_name == "local_file_search":
            return MCPToolExecution(tool_name, query, search_project_files(self.project_root, query))
        if tool_name == "git_repo_info":
            return MCPToolExecution(tool_name, query, self._git_repo_info())
        if tool_name == "safe_database_stats":
            return MCPToolExecution(tool_name, query, self._safe_database_stats())
        if tool_name == "web_search":
            return MCPToolExecution(tool_name, query, "网页搜索工具已注册但默认关闭，需要管理员启用并配置外部服务。")
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
