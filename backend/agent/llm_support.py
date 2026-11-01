"""LLM 与 token 用量管道：agent 层与 services 层共用的构造、归一化与统计帮助函数。

放在 agent 包（依赖链底层）：``apps.agent_api.services.llm_support`` 是本模块的
再导出，历史导入路径不受影响。这些逻辑与具体业务无关（RAG Agent、博客 Agent、
写作助手都可能使用），集中在此避免每个服务各写一份 base_url 修补和 token 统计。
"""

from __future__ import annotations

import os

TokenUsage = dict[str, int]


def normalized_openai_base_url(default: str) -> str:
    """修补缺少方案头的 base_url（https// -> https://）。"""
    base_url = os.getenv("OPENAI_BASE_URL", default)
    if base_url.startswith("https//"):
        return base_url.replace("https//", "https://", 1)
    if base_url.startswith("http//"):
        return base_url.replace("http//", "http://", 1)
    return base_url


def build_openai_chat(*, api_key: str, model: str, base_url: str, temperature: float = 0):
    """构造 ChatOpenAI；api_key 为空时返回 None（调用方走本地降级路径）。"""
    from langchain_openai import ChatOpenAI

    if not api_key:
        return None
    # SDK-internal retries do not expose per-attempt usage to LangChain callbacks.
    # Keep attempts observable at the caller boundary instead of silently hiding them.
    return ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=temperature, max_retries=0)


def empty_token_usage() -> TokenUsage:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def merge_token_usage(left: TokenUsage, right: TokenUsage) -> TokenUsage:
    return {
        "prompt_tokens": left.get("prompt_tokens", 0) + right.get("prompt_tokens", 0),
        "completion_tokens": left.get("completion_tokens", 0) + right.get("completion_tokens", 0),
        "total_tokens": left.get("total_tokens", 0) + right.get("total_tokens", 0),
    }


def extract_token_usage(message) -> TokenUsage:
    """从 LangChain 消息读取 token 用量，兼容两种 metadata 形态。"""
    usage = getattr(message, "usage_metadata", None)
    if usage:
        return {
            "prompt_tokens": int(usage.get("input_tokens", 0)),
            "completion_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }
    response_metadata = getattr(message, "response_metadata", {}) or {}
    token_usage = response_metadata.get("token_usage") or {}
    return {
        "prompt_tokens": int(token_usage.get("prompt_tokens", 0)),
        "completion_tokens": int(token_usage.get("completion_tokens", 0)),
        "total_tokens": int(token_usage.get("total_tokens", 0)),
    }
