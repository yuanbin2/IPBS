"""联网回答合成：把不可信的网页搜索上下文交给模型生成带来源标注的答案。

搜索结果是外部不可信数据，只能作为资料、不能当作指令；模型不可用或生成
失败时，原样返回真实搜索结果，不编造内容。
"""

from __future__ import annotations

from .agent_types import AgentResponse, ConversationHistory, ToolResult
from .llm_support import empty_token_usage, extract_token_usage
from .query_rewriting import format_history
from .rag_prompts import INTERNET_ANSWER_PROMPT


def answer_with_external_context(
    llm,
    message: str,
    context: str,
    tool_call: ToolResult,
    history: ConversationHistory | None = None,
) -> AgentResponse:
    """Synthesize an answer from explicitly enabled, untrusted web context."""
    if llm is None:
        return AgentResponse(
            answer=f"模型服务不可用，先返回真实网页搜索结果：\n\n{context}",
            tool_calls=[tool_call],
            sources=[],
            trace=["internet_search -> completed", "internet_generate -> model unavailable"],
            route="internet",
            token_usage=empty_token_usage(),
        )
    try:
        final_message = (INTERNET_ANSWER_PROMPT | llm).invoke(
            {"message": message, "context": context, "history": format_history(history or [])}
        )
        return AgentResponse(
            answer=str(final_message.content),
            tool_calls=[tool_call],
            sources=[],
            trace=["internet_search -> completed", "internet_generate -> completed"],
            route="internet",
            token_usage=extract_token_usage(final_message),
        )
    except Exception as exc:
        return AgentResponse(
            answer=f"网页搜索已完成，但模型生成失败，先返回搜索结果：\n\n{context}",
            tool_calls=[tool_call],
            sources=[],
            trace=[
                "internet_search -> completed",
                f"internet_generate -> failed: {type(exc).__name__}: {str(exc)[:200]}",
            ],
            route="internet",
            token_usage=empty_token_usage(),
        )
