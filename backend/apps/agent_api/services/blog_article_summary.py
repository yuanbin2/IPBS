"""整篇文章的顺序读取与分层摘要（map-reduce）。

向量检索把切片当独立记录，问「这篇文章讲了什么」时必须按原文顺序读完整篇。
这里按 chunk 顺序分批做 map 摘要，再 reduce 成整体概述；LLM 不可用时退回到
基于标题结构的确定性概览。
"""

from __future__ import annotations

import re

from langchain_core.prompts import ChatPromptTemplate

from agent.model_accounting import model_purpose

from ..models import BlogArticle
from .llm_support import empty_token_usage, extract_token_usage, merge_token_usage
from .rag import split_text

SUMMARY_BATCH_CHARS = 9000

MAP_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "你正在按原文顺序阅读一篇长博客。请完整提取当前部分的主题、关键知识点、"
                "步骤、示例和结论；不要只总结开头，不要添加原文没有的信息。"
            ),
        ),
        ("human", "文章标题：{title}\n\n当前部分：\n{content}\n\n请输出结构化的阶段摘要。"),
    ]
)

REDUCE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "你已经顺序读完一篇博客的所有部分。请综合所有阶段摘要，回答这篇文章讲了什么。"
                "覆盖全文而不是只覆盖相似片段，合并重复内容，按主题组织，并说明文章的最终结论或实践建议。"
                "只能依据给定摘要回答，结尾使用 [1] 引用该文章。"
            ),
        ),
        ("human", "文章标题：{title}\n\n全部阶段摘要：\n{summaries}\n\n请生成完整文章概述。"),
    ]
)


def ordered_article_chunks(article: BlogArticle) -> list[str]:
    """优先使用已入库的有序切片，缺失时退回复现切分。"""
    if article.knowledge_document_id:
        chunks = list(article.knowledge_document.chunks.order_by("chunk_index").values_list("content", flat=True))
        if chunks:
            return chunks
    return split_text(article.content)


def summarize_full_article(llm, article: BlogArticle) -> tuple[str, dict[str, int], int]:
    """按顺序分批 map 再 reduce，返回 (答案, token 用量, 片段数)。"""
    chunks = ordered_article_chunks(article)
    if not chunks:
        raise ValueError("article has no readable content")

    batches: list[str] = []
    current: list[str] = []
    current_chars = 0
    for index, chunk in enumerate(chunks, start=1):
        labeled = f"[片段 {index}/{len(chunks)}]\n{chunk}"
        if current and current_chars + len(labeled) > SUMMARY_BATCH_CHARS:
            batches.append("\n\n".join(current))
            current = []
            current_chars = 0
        current.append(labeled)
        current_chars += len(labeled)
    if current:
        batches.append("\n\n".join(current))

    partial_summaries: list[str] = []
    usage = empty_token_usage()
    for batch in batches:
        with model_purpose("blog_summary_map"):
            message = (MAP_PROMPT | llm).invoke({"title": article.title, "content": batch})
        partial_summaries.append(str(message.content))
        usage = merge_token_usage(usage, extract_token_usage(message))

    with model_purpose("blog_summary_reduce"):
        final_message = (REDUCE_PROMPT | llm).invoke(
            {
                "title": article.title,
                "summaries": "\n\n".join(
                    f"第 {index} 部分：\n{summary}" for index, summary in enumerate(partial_summaries, start=1)
                ),
            }
        )
    usage = merge_token_usage(usage, extract_token_usage(final_message))
    return str(final_message.content), usage, len(chunks)


def fallback_full_article_summary(article: BlogArticle) -> str:
    """无可用 LLM 时，基于全文标题结构给出确定性概览。"""
    headings = []
    for heading in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$", article.content):
        clean_heading = re.sub(r"[`*_]", "", heading).strip()
        if clean_heading and clean_heading not in headings:
            headings.append(clean_heading)

    lines = [f"《{article.title}》是一篇完整文章。"]
    if article.summary.strip():
        lines.append(article.summary.strip())
    if headings:
        lines.append("文章按顺序覆盖这些部分：")
        lines.extend(f"- {heading}" for heading in headings[:30])
    lines.append(
        "当前未配置可用的大模型，因此这里展示的是基于全文标题结构提取的概览；"
        "已读取整篇文章，而不是只读取开头的检索片段。[1]"
    )
    return "\n\n".join(lines)
