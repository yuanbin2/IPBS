"""上下文查询重写：把含指代的追问改写成可独立搜索/检索的查询。

LLM 不可用或没有历史时，退回到确定性的拼接策略；两个入口（网页搜索、
知识库检索）各自带针对性的系统提示词。
"""

from __future__ import annotations

import re

from langchain_core.prompts import ChatPromptTemplate

from .agent_types import ConversationHistory
from .model_accounting import model_purpose

MAX_REWRITTEN_CHARS = 160

WEB_SEARCH_REWRITE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是搜索查询改写器。结合最近对话，把当前问题改写成一条可独立搜索的精准查询。"
            "解析‘它、这个、那、上面’等指代，保留实体、版本、时间、地区和官方来源要求。"
            "只输出检索式，不回答问题，不添加解释，最多 160 个字符。",
        ),
        ("human", "最近对话：\n{history}\n\n当前问题：{message}"),
    ]
)

RETRIEVAL_REWRITE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是知识库检索查询改写器。结合最近对话，把当前追问改写成可独立检索的问题。"
            "必须解析‘他、她、它、这个、那个、其、上述’等指代并保留人物姓名、机构、主题等关键实体。"
            "只输出检索问题，不回答，不添加解释，最多 160 个字符。",
        ),
        ("human", "最近对话：\n{history}\n\n当前问题：{message}"),
    ]
)


def fallback_contextual_search_query(message: str, history: ConversationHistory) -> str:
    follow_up_markers = ["它", "他", "这个", "那个", "那", "呢", "继续", "上述", "上面", "刚才"]
    # Search-prefixed messages are standalone queries, not follow-ups
    search_prefixes = [
        "搜索",
        "检索",
        "查找",
        "查询",
        "网页搜索",
        "网络搜索",
        "在网上",
        "在网络",
        "用网络",
        "用网页",
    ]
    has_search_prefix = any(prefix in message for prefix in search_prefixes)
    is_follow_up = not has_search_prefix and (
        len(message.strip()) <= 24 or any(marker in message for marker in follow_up_markers)
    )
    if not is_follow_up:
        return message.strip()
    previous_questions = [item.get("content", "").strip() for item in history if item.get("role") == "user"]
    if not previous_questions:
        return message.strip()
    context = " ".join(previous_questions[-2:])
    if "比较" in message or "对比" in message:
        titles = _recent_source_titles(history)
        if titles:
            context = f"来源标题：{'、'.join(titles)} {context}"
    current = message.strip()
    return f"{context[: max(0, 239 - len(current))]} {current}"[:240]


def _rewrite(llm, prompt, message: str, history: ConversationHistory, fallback: str) -> str:
    try:
        with model_purpose("query_rewrite"):
            rewritten = str((prompt | llm).invoke({"history": format_history(history), "message": message}).content)
        rewritten = re.sub(r"[\r\n]+", " ", rewritten).strip(" `\"'，。")
        return rewritten[:MAX_REWRITTEN_CHARS] or fallback
    except Exception:
        return fallback


def rewrite_web_search_query(llm, message: str, history: ConversationHistory | None = None) -> str:
    """Turn a contextual follow-up into a standalone web-search query."""
    history = history or []
    fallback = fallback_contextual_search_query(message, history)
    if llm is None or not history:
        return fallback
    return _rewrite(llm, WEB_SEARCH_REWRITE_PROMPT, message, history, fallback)


def preserve_query_entities(original: str, rewritten: str) -> str:
    """改写结果丢掉原问题实体时，退回原问题（B-055）。

    知识库检索靠中文姓名/机构名做标题与内容加成。LLM 改写是非确定性的，实测同一问题
    会产出不含「卫晓斌」的英文串（如 `Wei Xiaobin university affiliation institution`），
    检索随即完全落空。这里做一次确定性校验：原问题能抽出实体、而改写串丢了其中任何一个，
    就直接用原问题检索，不让非确定性的改写决定检索成败。
    """
    if not rewritten or rewritten == original:
        return rewritten or original
    try:
        from apps.agent_api.services.rag import query_entity_terms
    except Exception:  # 脱离 Django 的纯函数调用场景不做拦截
        return rewritten
    entities = query_entity_terms(original)
    if entities and any(entity not in rewritten for entity in entities):
        return original
    return rewritten


def rewrite_retrieval_query(llm, message: str, history: ConversationHistory | None = None) -> str:
    """Resolve follow-up references before searching the private knowledge base."""
    history = history or []
    fallback = fallback_contextual_search_query(message, history)
    if llm is None or not history or fallback == message.strip():
        return fallback
    rewritten = preserve_query_entities(message, _rewrite(llm, RETRIEVAL_REWRITE_PROMPT, message, history, fallback))
    if "比较" in message or "对比" in message:
        titles = _recent_source_titles(history)
        if titles and any(title not in rewritten for title in titles):
            return fallback
    return rewritten


def format_history(history: ConversationHistory) -> str:
    return _format_history(history, max_chars=2400, include_source_titles=True)


def format_answer_history(history: ConversationHistory) -> str:
    """Bounded dialogue context for answer generation; source text stays in current retrieval results."""
    return _format_history(history, max_chars=4000, include_source_titles=True)


def _recent_source_titles(history: ConversationHistory) -> list[str]:
    titles: list[str] = []
    for item in history[-10:]:
        for source in item.get("sources") or []:
            if not isinstance(source, dict):
                continue
            title = str(source.get("document_title", "")).strip()[:80]
            if title and title not in titles:
                titles.append(title)
    return titles[-4:]


def _format_history(history: ConversationHistory, *, max_chars: int, include_source_titles: bool) -> str:
    if not history:
        return "（新会话，无历史消息）"
    labels = {"user": "用户", "agent": "助手"}
    lines = []
    remaining = max_chars
    for item in reversed(history[-10:]):
        role = str(item.get("role", ""))
        content = str(item.get("content", ""))[:800]
        line = f"{labels.get(role, '消息')}：{content}"
        if include_source_titles:
            titles = _recent_source_titles([item])
            if titles:
                line += f"\n本轮来源标题：{'、'.join(titles)}"
        if remaining <= 0:
            break
        lines.append(line[:remaining])
        remaining -= min(len(line), remaining) + 1
    return "\n".join(reversed(lines))
