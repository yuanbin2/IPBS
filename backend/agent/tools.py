"""Agent 可调用的确定性工具与知识检索适配函数。

该层把底层实现包装成统一 ToolResult，供 LangGraph 节点记录调用轨迹。
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import tool


@dataclass(frozen=True)
class ToolResult:
    name: str
    input: str
    output: str


class SafeCalculator:
    _operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def run(self, expression: str) -> str:
        try:
            parsed = ast.parse(expression, mode="eval")
            value = self._eval(parsed.body)
        except Exception as exc:
            return f"计算失败：{exc}"
        return f"{expression} = {value}"

    def _eval(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in self._operators:
            left = self._eval(node.left)
            right = self._eval(node.right)
            return self._operators[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._operators:
            return self._operators[type(node.op)](self._eval(node.operand))
        raise ValueError("只支持数字和基础四则运算")


def search_project_files(project_root: Path, query: str) -> str:
    sources = [
        project_root / "README.md",
        project_root / "docs" / "day-01-blog.md",
        project_root / "docs" / "architecture.md",
        project_root / "docs" / "day-02-notes.md",
        project_root / "docs" / "day-03-notes.md",
    ]
    matches: list[str] = []
    terms = [term.lower() for term in query.split() if term.strip()]

    for source in sources:
        if not source.exists():
            continue
        text = source.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            line_lower = line.lower()
            if not terms or any(term in line_lower for term in terms):
                cleaned = line.strip("#- ` ")
                if cleaned:
                    matches.append(f"{source.name}: {cleaned}")
            if len(matches) >= 5:
                break
        if len(matches) >= 5:
            break

    if not matches:
        return "项目 README、架构文档和学习笔记中没有找到直接匹配内容。"
    return "\n".join(matches)


def search_knowledge(query: str, project_root: Path) -> str:
    try:
        from apps.agent_api.services.rag import format_search_results, search_knowledge_base

        results = search_knowledge_base(query, limit=5)
        if results:
            return format_search_results(results)
    except Exception as exc:
        project_matches = search_project_files(project_root, query)
        return f"知识库检索暂时不可用：{exc}\n\n项目文件兜底：\n{project_matches}"

    project_matches = search_project_files(project_root, query)
    return f"知识库没有检索到高相关片段。\n\n项目文件兜底：\n{project_matches}"


def build_langchain_tools(project_root: Path):
    calculator = SafeCalculator()

    @tool
    def knowledge_search(query: str) -> str:
        """Search uploaded knowledge-base documents and local project notes for RAG context."""
        return search_knowledge(query, project_root)

    @tool
    def current_user_profile(_: str = "") -> str:
        """Return the current learner profile and project context."""
        return (
            "当前用户正在构建企业知识智能体平台 + 个人博客智能体系统；"
            "技术路线是 Vue 3 + Django + LangChain/LangGraph + RAG + MCP。"
        )

    @tool("calculator")
    def calculator_tool(expression: str) -> str:
        """Evaluate a simple arithmetic expression, such as 12 * 8."""
        return calculator.run(expression)

    return [knowledge_search, current_user_profile, calculator_tool]
