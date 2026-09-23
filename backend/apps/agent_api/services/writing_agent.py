"""Markdown writing assistant used by the private blog editor."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI


WRITING_MODES = {
    "task_list": (
        "把写作目标拆成可执行的 Markdown 任务清单。使用 `- [ ]`，按资料准备、写作、"
        "校对等阶段分组；每项要具体、简短。"
    ),
    "outline": (
        "生成可直接放进正文的 Markdown 大纲。使用二级、三级标题，并在每个标题下放一条"
        "简短的写作提示；不要虚构正文事实。"
    ),
    "draft": (
        "根据用户要求和已有内容生成一版结构完整的 Markdown 草稿。缺少事实时使用"
        "`<!-- TODO: 补充…… -->`，不要编造数据、经历或引用。"
    ),
    "improve": (
        "润色并重组已有 Markdown，保留原意、代码块、链接和事实；改善标题层级、段落衔接"
        "与表达。只返回修改后的完整 Markdown。"
    ),
}


class WritingAgentConfigurationError(RuntimeError):
    """Raised when no API key is available for the writing agent."""


@dataclass(frozen=True)
class WritingAgentResult:
    markdown: str
    mode: str
    model: str
    api_key_source: str


class BlogWritingAgent:
    """Small, editor-only agent that produces Markdown for human revision."""

    def __init__(self):
        dedicated_key = os.getenv("BLOG_WRITING_AGENT_API_KEY", "").strip()
        shared_key = os.getenv("OPENAI_API_KEY", "").strip()
        api_key = dedicated_key or shared_key
        if not api_key:
            raise WritingAgentConfigurationError(
                "写作助手尚未配置 API Key。请配置 BLOG_WRITING_AGENT_API_KEY 或 OPENAI_API_KEY。"
            )

        self.api_key_source = "dedicated" if dedicated_key else "shared"
        self.model = (
            os.getenv("BLOG_WRITING_AGENT_MODEL", "").strip()
            or os.getenv("OPENAI_MODEL", "").strip()
            or "gpt-4o-mini"
        )
        base_url = (
            os.getenv("BLOG_WRITING_AGENT_BASE_URL", "").strip()
            or os.getenv("OPENAI_BASE_URL", "").strip()
            or "https://api.openai.com/v1"
        )
        self.llm = ChatOpenAI(
            model=self.model,
            api_key=api_key,
            base_url=self._normalize_base_url(base_url),
            temperature=0.35,
        )

    def generate(self, *, mode: str, instruction: str, draft: dict[str, str]) -> WritingAgentResult:
        if mode not in WRITING_MODES:
            raise ValueError("unsupported writing mode")

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "你是博客编辑器里的 Markdown 写作助手。你的产出是给作者继续修改的笔记，"
                        "不是自动发布的最终文章。严格只输出 Markdown，不要用三反引号包裹整份结果，"
                        "不要解释生成过程。不要虚构事实、数据、链接、引用或作者经历；资料不足时"
                        "明确留下 TODO。语言跟随用户要求，默认使用简洁自然的中文。\n\n"
                        "当前任务：{mode_instruction}"
                    ),
                ),
                (
                    "human",
                    (
                        "写作要求：\n{instruction}\n\n"
                        "文章标题：{title}\n"
                        "摘要：{summary}\n"
                        "分类：{category}\n"
                        "标签：{tags}\n\n"
                        "已有 Markdown：\n{content}"
                    ),
                ),
            ]
        )
        message = (prompt | self.llm).invoke(
            {
                "mode_instruction": WRITING_MODES[mode],
                "instruction": instruction or "请结合标题和已有草稿完成当前任务。",
                "title": draft.get("title", "") or "（未填写）",
                "summary": draft.get("summary", "") or "（未填写）",
                "category": draft.get("category", "") or "（未填写）",
                "tags": draft.get("tags", "") or "（未填写）",
                "content": draft.get("content", "") or "（当前没有正文）",
            }
        )
        markdown = self._clean_markdown(str(message.content))
        if not markdown:
            raise RuntimeError("写作助手没有返回内容")
        return WritingAgentResult(
            markdown=markdown,
            mode=mode,
            model=self.model,
            api_key_source=self.api_key_source,
        )

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        if base_url.startswith("https//"):
            return base_url.replace("https//", "https://", 1)
        if base_url.startswith("http//"):
            return base_url.replace("http//", "http://", 1)
        return base_url

    @staticmethod
    def _clean_markdown(value: str) -> str:
        text = value.strip()
        fenced = re.fullmatch(r"```(?:markdown|md)?\s*\n([\s\S]*?)\n```", text, flags=re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
        return text[:30000]
