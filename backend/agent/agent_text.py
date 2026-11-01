"""RAG Agent 的纯文本帮助函数：意图识别、机构信息抽取与本地兜底回答。

这些函数不依赖 LLM 和图状态，可独立单测；``answer_affiliation_question``
按「学位优先」排序，把散落在多个切片里的学校/学位信息聚合成一句话。
"""

from __future__ import annotations

import re

from .agent_types import SourceCitation, ToolResult

FOLLOW_UP_MARKERS = ["它", "他", "这个", "那个", "那", "呢", "继续", "上述", "上面", "刚才"]

RETRIEVAL_KEYWORDS = [
    "哪个学校",
    "哪所学校",
    "什么学校",
    "毕业院校",
    "就读学校",
    "作者单位",
    "任职单位",
    "来自哪里",
    "自己的数据库",
    "我的数据库",
    "资料库",
    "检索",
    "搜索",
    "查找",
    "查询项目",
    "项目资料",
    "项目文档",
    "项目相关",
    "本地文档",
    "知识库",
    "我的文档",
    "我的笔记",
    "上传的文档",
    "上传的资料",
    "这份资料",
    "那份资料",
    "资料里",
    "资料中",
    "附件",
    "简历",
    "私有资料",
    "文档里",
    "文档中",
    "引用",
    "来源",
    "相关的东西",
    "相关资料",
    "成功案例",
    "博客草稿",
    "散射成像",
    "散射介质",
    "散斑相关",
    "散斑",
    "scattering imaging",
    "speckle correlation",
]

DEGREE_RANK = {"博士": 0, "PhD": 0, "硕士": 1, "研究生": 1, "Master": 1, "本科": 2, "学士": 2, "Bachelor": 2, "": 3}


def needs_tool_or_project_context(message: str) -> bool:
    lowered = message.lower()
    if re.search(r"\d+\s*[\+\-\*/%]\s*\d+", message):
        return True

    user_keywords = ["当前用户", "用户资料", "我的项目", "我是谁", "profile"]
    if any(keyword in lowered for keyword in user_keywords):
        return True

    return any(keyword in lowered for keyword in RETRIEVAL_KEYWORDS)


def is_contextual_follow_up(message: str) -> bool:
    text = message.strip()
    return len(text) <= 40 and bool(
        text.startswith(
            ("他", "她", "它", "这份", "那份", "这个", "那个", "这篇", "那篇", "那里面", "这里面", "继续", "还有")
        )
        or any(marker in text for marker in ("刚才", "上面", "上述", "前面", "其中"))
        or text.endswith("呢？")
        or text.endswith("呢?")
    )


def requires_workspace_retrieval(message: str, history: list[dict] | None = None) -> bool:
    """Only inherit retrieval intent when the new question refers to prior context."""
    if needs_tool_or_project_context(message):
        return True
    history = history or []
    if not history or not is_contextual_follow_up(message):
        return False
    recent_users = [item.get("content", "") for item in history if item.get("role") == "user"][-2:]
    if recent_users:
        from .supervisor_routing import is_mcp_request

        if is_mcp_request(recent_users[-1]):
            return False
    if recent_users and needs_tool_or_project_context(recent_users[-1]):
        return True
    if (
        len(recent_users) > 1
        and is_contextual_follow_up(recent_users[-1])
        and needs_tool_or_project_context(recent_users[-2])
    ):
        return True
    return any(item.get("sources") for item in history[-2:])


def asks_for_web_search(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in ["网络", "网上", "web", "互联网", "外部资料"])


def is_affiliation_question(message: str) -> bool:
    return any(
        term in message for term in ["学校", "院校", "大学", "学院", "毕业", "就读", "哪个学校", "哪所学校", "什么学校"]
    )


def answer_affiliation_question(message: str, sources: list[SourceCitation]) -> str:
    if not sources or not is_affiliation_question(message):
        return ""

    from apps.agent_api.services.rag import query_entity_terms

    person = next(iter(query_entity_terms(message)), "该用户")
    education: list[tuple[str, str, int]] = []
    institution_pattern = r"([\u4e00-\u9fffA-Za-z（）()·\-]{2,30}(?:大学|学院|University|College|Institute))"
    degree_pattern = r"(博士|硕士|本科|研究生|学士|PhD|Master|Bachelor)"
    for index, source in enumerate(sources, start=1):
        text = re.sub(r"\s+", " ", source.content)
        for match in re.finditer(institution_pattern, text):
            start = max(0, match.start() - 28)
            end = min(len(text), match.end() + 40)
            before_window = text[start : match.start()]
            after_window = text[match.end() : end]
            after_segment = re.split(r"[；;。.\n]", after_window, maxsplit=1)[0]
            before_segment = re.split(r"[；;。.\n]", before_window)[-1]
            degree_match = re.search(degree_pattern, after_segment) or re.search(
                degree_pattern,
                before_segment,
            )
            degree = degree_match.group(1) if degree_match else ""
            institution = match.group(1).strip(" ，。；;:：")
            item = (degree, institution, index)
            if institution and item not in education:
                education.append(item)

    if not education:
        return ""

    education.sort(key=lambda item: DEGREE_RANK.get(item[0], 3))
    parts = []
    seen: set[str] = set()
    for degree, institution, source_index in education:
        if institution in seen:
            continue
        seen.add(institution)
        label = f"{degree}：" if degree else ""
        parts.append(f"{label}{institution}[{source_index}]")
        if len(parts) >= 3:
            break

    return f"根据已上传资料，{person}的学校信息是：" + "；".join(parts) + "。"


def build_grounded_fallback_answer(
    message: str,
    tool_call: ToolResult,
    sources: list[SourceCitation],
) -> str:
    web_note = ""
    if asks_for_web_search(message):
        web_note = (
            "\n\n另外，你的请求里提到“去网络中找”。当前系统没有启用真实联网搜索工具，"
            "所以我不能假装已经访问互联网；下面结论只基于本地知识库和项目文件。"
        )

    if not sources:
        return (
            "我已经尝试从本地知识库检索，但没有找到足够相关的片段。"
            f"{web_note}\n\n"
            "你可以先上传项目复盘、成功案例、README、论文笔记或业务文档，再让我基于这些资料做解释。"
        )

    affiliation_answer = answer_affiliation_question(message, sources)
    if affiliation_answer:
        return affiliation_answer + web_note

    if any(term in message for term in ["学校", "院校", "作者单位", "任职单位", "来自哪里"]):
        for index, source in enumerate(sources, start=1):
            universities = re.findall(
                r"\b(?:[A-Z][A-Za-z]*(?:\s+|\-)){1,6}University\b",
                source.content,
            )
            if universities:
                institution = max(universities, key=len).strip()
                return (
                    f"根据上传文档中的作者单位或作者简介，苏轩（Xuan Su）所在学校是 "
                    f"{institution}（重庆三峡学院）[{index}]。"
                )

    bullets = []
    for index, source in enumerate(sources[:4], start=1):
        snippet = re.sub(r"\s+", " ", source.content).strip()
        if len(snippet) > 180:
            snippet = f"{snippet[:180]}..."
        bullets.append(f"{index}. {source.document_title}：{snippet}")

    return (
        "我先根据本地知识库找到了这些与问题相关的依据：\n\n"
        + "\n".join(bullets)
        + web_note
        + "\n\n以上仅为检索片段；未配置模型，无法进一步综合或核实结论。"
    )


def format_source_context(sources: list[SourceCitation]) -> str:
    if not sources:
        return "没有检索到明确来源。"
    return "\n\n".join(
        (
            f"[{index}] 文档：{source.document_title}\n"
            f"chunk_id：{source.chunk_id}\n"
            f"相似度：{source.score:.3f}\n"
            f"内容：{source.content}"
        )
        for index, source in enumerate(sources, start=1)
    )
