"""RAG 检索与确定性工具的管道函数。

显式传参（不依赖 Agent 实例状态），便于单测；向量检索失败时降级到
项目文件搜索，保证 Agent 永远有可用的「知识检索」工具轨迹。
"""

from __future__ import annotations

import re

from .agent_types import SourceCitation, ToolResult
from .model_accounting import model_purpose
from .query_rewriting import preserve_query_entities
from .rag_prompts import RAG_QUERY_REWRITE_PROMPT
from .telemetry import observe_stage
from .tools import SafeCalculator, search_knowledge

USER_PROFILE_ANSWER = (
    "当前用户正在构建企业知识智能体平台 + 个人博客智能体系统；"
    "技术路线是 Vue 3 + Django + LangChain/LangGraph + RAG + MCP。"
)


def grade_source_relevance(sources: list[SourceCitation], minimum_score: float) -> tuple[float, list[SourceCitation]]:
    """Apply the same relevance boundary in the graph and its error fallback."""
    best_score = max((source.score for source in sources), default=0.0)
    return best_score, sources if sources and best_score >= minimum_score else []


def run_required_non_rag_tool(message: str) -> ToolResult | None:
    """计算器与「当前用户」两类确定性工具优先于向量检索短路执行。"""
    if re.search(r"\d+\s*[\+\-\*/%]\s*\d+", message):
        expression = re.search(r"[\d\s\+\-\*/%\.\(\)]+", message)
        value = expression.group(0).strip() if expression else message
        return ToolResult("calculator", value, SafeCalculator().run(value))

    lowered = message.lower()
    user_keywords = ["当前用户", "用户资料", "我的项目", "我是谁", "profile"]
    if any(keyword in lowered for keyword in user_keywords):
        return ToolResult("current_user_profile", message, USER_PROFILE_ANSWER)

    return None


def rewrite_query_text(llm, message: str) -> str:
    """把用户问题改写成适合知识库检索的短查询；无 LLM 时用确定性后缀。"""
    if llm is None:
        return f"{message} 相关定义 背景 方法 结论"

    with model_purpose("retrieval_query_rewrite"):
        rewritten_message = (RAG_QUERY_REWRITE_PROMPT | llm).invoke({"message": message})
    rewritten = str(rewritten_message.content).strip() or f"{message} 相关资料"
    # B-055：改写不得丢掉原问题里的实体，否则回退到原问题。
    return preserve_query_entities(message, rewritten)


@observe_stage("retrieval")
def search_sources(query: str, *, workspace_key: str, project_root) -> tuple[ToolResult, list[SourceCitation]]:
    try:
        from apps.agent_api.services.rag import (
            expand_search_results_with_neighbors,
            format_search_results,
            search_knowledge_base,
        )

        results = search_knowledge_base(query, limit=5, workspace_key=workspace_key)
        results = expand_search_results_with_neighbors(
            results,
            neighbor_window=1,
            max_results=12,
        )
        sources = [
            SourceCitation(
                document_id=result.document_id,
                document_title=result.document_title,
                chunk_id=result.chunk_id,
                chunk_index=result.chunk_index,
                score=result.score,
                content=result.content,
            )
            for result in results
        ]
        return ToolResult("knowledge_search", query, format_search_results(results)), sources
    except Exception as exc:
        output = search_knowledge(query, project_root)
        return ToolResult("knowledge_search", query, f"知识库检索暂时不可用：{exc}\n\n{output}", ok=False), []
