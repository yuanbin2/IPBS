"""访客 Agent 的公开来源检索。

只返回已发布博客与白名单内的公开项目材料；知识库检索结果会再用
「已发布文章的 knowledge_document_id」过滤，未公开文档不会漏出。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.db.models import Q

from ..models import BlogArticle
from .rag import expand_search_results_with_neighbors, search_knowledge_base

PUBLIC_README_FILES = [
    "README.md",
    "docs/architecture.md",
    "docs/day-06-notes.md",
]

MAX_PUBLIC_SOURCES = 8


@dataclass(frozen=True)
class BlogAgentSource:
    title: str
    kind: str
    content: str
    score: float = 0.0
    url: str = ""
    document_id: int | None = None
    chunk_index: int | None = None


def is_system_tech_stack_question(question: str) -> bool:
    lowered = question.lower()
    has_subject = any(
        keyword in lowered for keyword in ["本系统", "本项目", "本博客", "博客系统", "这个项目", "技术栈"]
    )
    has_stack = any(keyword in lowered for keyword in ["技术栈", "使用了什么技术", "用了哪些技术", "系统架构"])
    return has_subject and has_stack


def search_public_blog_documents(question: str) -> list[BlogAgentSource]:
    public_document_ids = set(
        BlogArticle.objects.filter(
            status=BlogArticle.Status.PUBLISHED,
            knowledge_document_id__isnull=False,
        ).values_list("knowledge_document_id", flat=True)
    )
    if not public_document_ids:
        return []

    results = search_knowledge_base(question, limit=6)
    public_results = [result for result in results if result.document_id in public_document_ids]
    public_results = expand_search_results_with_neighbors(
        public_results,
        neighbor_window=1,
        max_results=12,
    )
    return [
        BlogAgentSource(
            title=result.document_title,
            kind="blog_knowledge",
            content=result.content,
            score=result.score,
            document_id=result.document_id,
            chunk_index=result.chunk_index,
        )
        for result in public_results
    ]


def search_articles(question: str) -> list[BlogAgentSource]:
    query = question.strip()
    terms = [term for term in re.split(r"[\s，。？！,.!?、]+", query) if len(term) >= 2]
    if is_system_tech_stack_question(question):
        terms = ["技术栈", "系统架构", "Vue", "Django"]
    articles = BlogArticle.objects.filter(status=BlogArticle.Status.PUBLISHED)
    if terms:
        condition = Q()
        for term in terms[:5]:
            condition |= Q(title__icontains=term) | Q(summary__icontains=term) | Q(content__icontains=term)
        articles = articles.filter(condition)
    else:
        articles = articles[:3]

    return [
        BlogAgentSource(
            title=article.title,
            kind="blog_article",
            content=f"{article.summary}\n\n{article.content[:700]}".strip(),
            url=f"/blog/{article.slug}",
            score=0.5,
            document_id=article.knowledge_document_id,
        )
        for article in articles.distinct()[:3]
    ]


def search_readme(project_root, question: str) -> list[BlogAgentSource]:
    terms = [term.lower() for term in re.split(r"[\s，。？！,.!?、]+", question) if len(term) >= 2]
    sources: list[BlogAgentSource] = []
    for relative_path in PUBLIC_README_FILES:
        path = project_root / relative_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]
        matched = []
        for paragraph in paragraphs:
            lowered = paragraph.lower()
            if not terms or any(term in lowered for term in terms):
                matched.append(paragraph)
            if len(matched) >= 2:
                break
        if matched:
            sources.append(
                BlogAgentSource(
                    title=relative_path,
                    kind="readme",
                    content="\n\n".join(matched)[:900],
                    score=0.35,
                )
            )
    return sources


def default_public_sources() -> list[BlogAgentSource]:
    sources: list[BlogAgentSource] = []
    latest_articles = BlogArticle.objects.filter(status=BlogArticle.Status.PUBLISHED)[:2]
    for article in latest_articles:
        sources.append(
            BlogAgentSource(
                title=article.title,
                kind="blog_article",
                content=f"{article.summary}\n\n{article.content[:500]}".strip(),
                url=f"/blog/{article.slug}",
                score=0.2,
                document_id=article.knowledge_document_id,
            )
        )
    return sources


def retrieve_public_sources(question: str) -> list[BlogAgentSource]:
    """检索模式刻意收窄为已发布博客内容，README 不静默混入来源。"""
    if is_system_tech_stack_question(question):
        sources = search_articles(question)
    else:
        sources = [*search_public_blog_documents(question), *search_articles(question)]
    unique: list[BlogAgentSource] = []
    seen: set[tuple[str, str, int | None, int | None]] = set()
    for source in sources:
        # 同一篇文章的多个切片有意保留：document/chunk 标识承载顺序关系。
        key = (source.kind, source.title, source.document_id, source.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
        if len(unique) >= MAX_PUBLIC_SOURCES:
            break
    return unique or default_public_sources()
