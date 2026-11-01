"""Agent 可调用的确定性工具与知识检索适配函数。

该层把底层实现包装成统一 ToolResult，供 LangGraph 节点记录调用轨迹。
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import tool


@dataclass(frozen=True)
class ToolResult:
    name: str
    input: str
    output: str
    # 显式成功标记：检索正文可能恰好含「失败/error」等词，不能用输出内容
    # 做关键词猜测；失败路径必须显式置 False。
    ok: bool = True


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


# 项目文档检索的范围与上限。老实现只硬编码 5 个文件（其中 3 个早已不存在），
# 实际可搜到的只有 README 一篇，因此改为扫描 docs/ 下全部 Markdown。
PROJECT_DOC_MAX_FILES = 200
PROJECT_DOC_MAX_BYTES = 512 * 1024
PROJECT_DOC_MAX_LINES = 200_000
PROJECT_DOC_MAX_MATCHES = 10
PROJECT_DOC_LINE_CHARS = 200
_SKIP_DIR_NAMES = {".git", "node_modules", ".venv", "__pycache__", "dist", "test-results"}
_CJK_RUN = re.compile(r"[一-鿿]+")


def collect_project_doc_files(project_root: Path) -> list[Path]:
    """根目录 README + docs/ 下全部 .md（递归，跳过构建产物目录，路径排序保证确定性）。"""
    sources: list[Path] = []
    readme = project_root / "README.md"
    if readme.is_file():
        sources.append(readme)
    docs_dir = project_root / "docs"
    if docs_dir.is_dir():
        for path in sorted(docs_dir.rglob("*.md")):
            if not path.is_file() or _SKIP_DIR_NAMES.intersection(path.parts):
                continue
            sources.append(path)
    return sources[:PROJECT_DOC_MAX_FILES]


def split_search_terms(query: str) -> list[str]:
    """空格分词；中文串再补充 2 字滑窗，避免整句查询零召回。"""
    terms: list[str] = []
    for raw in query.split():
        token = raw.strip().lower()
        if not token:
            continue
        terms.append(token)
        for run in _CJK_RUN.findall(token):
            if len(run) >= 3:
                terms.extend(run[index : index + 2] for index in range(len(run) - 1))
    # 去重并保持顺序，避免出现大量重复 2-gram 把评分拉偏。
    return list(dict.fromkeys(terms))


def _score_line(line_lower: str, name_lower: str, terms: list[str]) -> int:
    hits = [term for term in terms if term in line_lower]
    if not hits:
        return 0
    score = len(hits) * 10 + sum(line_lower.count(term) for term in hits)
    if any(term in name_lower for term in terms):
        score += 5
    return score


def search_project_files(project_root: Path, query: str) -> str:
    sources = collect_project_doc_files(project_root)
    terms = split_search_terms(query)
    if not terms:
        preview = "\n".join(f"- {path.relative_to(project_root).as_posix()}" for path in sources[:10])
        return f"请提供检索关键词。当前可检索 {len(sources)} 个 Markdown 文档，例如：\n{preview}"

    matches: list[tuple[int, str, int, str]] = []
    scanned_lines = 0
    for source in sources:
        try:
            if source.stat().st_size > PROJECT_DOC_MAX_BYTES:
                continue
            text = source.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = source.relative_to(project_root).as_posix()
        name_lower = rel.lower()
        for lineno, line in enumerate(text.splitlines(), start=1):
            scanned_lines += 1
            if scanned_lines > PROJECT_DOC_MAX_LINES:
                break
            cleaned = line.strip("#- ` *>")  # noqa: B005 - 去的是一组 markdown 符号字符
            if not cleaned:
                continue
            score = _score_line(cleaned.lower(), name_lower, terms)
            # 同时命中全部关键词的行优先级最高，避免中文 2-gram 把噪声顶上来。
            if score and all(term in cleaned.lower() for term in query.split()):
                score += 1000
            if score:
                matches.append((score, rel, lineno, cleaned[:PROJECT_DOC_LINE_CHARS]))
        if scanned_lines > PROJECT_DOC_MAX_LINES:
            break

    if not matches:
        return f"docs 与 README 的 {len(sources)} 个 Markdown 文档中没有找到匹配「{query.strip()}」的内容。"

    # 同分按 (文件, 行号) 升序，保证同样的查询每次输出一致。
    ordered = sorted(matches, key=lambda item: (-item[0], item[1], item[2]))[:PROJECT_DOC_MAX_MATCHES]
    lines = [f"{rel}:{lineno}: {text}" for _, rel, lineno, text in ordered]
    return f"检索 {len(sources)} 个项目文档，命中 {len(ordered)} 条（按相关度排序）：\n" + "\n".join(lines)


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
