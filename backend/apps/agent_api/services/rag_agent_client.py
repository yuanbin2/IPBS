"""RAG-Agent 外部知识源客户端（B051 后续）。

将问题转发给本机运行的 rag-agent 服务（http://127.0.0.1:18080/query），
以 blog 租户凭据检索 blog 租户隔离知识，返回与 BlogAgentAnswer 同构的结果。

fail-open 契约：rag-agent 不可达/超时/异常时抛出 RagAgentError，
由调用方（blog_agent view）捕获并降级回站内检索——宁可回退不可中断问答。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import requests

# 对本机 rag-agent 的调用禁止走系统/环境代理（Clash、沙箱注入的
# HTTP_PROXY 等）；127.0.0.1 永远直连。
_session = requests.Session()
_session.trust_env = False

from ..services.blog_agent import BlogAgentAnswer
from ..services.blog_public_retrieval import BlogAgentSource
from .llm_support import empty_token_usage


class RagAgentError(RuntimeError):
    """rag-agent 调用失败（网络/超时/非 200/格式错误）。"""


@dataclass
class RagAgentSettings:
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "RagAgentSettings":
        return cls(
            base_url=os.getenv("RAG_AGENT_BASE_URL", "http://127.0.0.1:18080").rstrip("/"),
            api_key=os.getenv("RAG_AGENT_API_KEY", "").strip(),
            timeout_seconds=float(os.getenv("RAG_AGENT_TIMEOUT_SECONDS", "30")),
        )


@dataclass
class RagAgentResult:
    answer: str
    sources: list[dict] = field(default_factory=list)
    refused: bool = False


def query_rag_agent(question: str, top_k: int = 5) -> RagAgentResult:
    """调用 rag-agent /query；返回结构化结果。失败抛 RagAgentError。"""
    cfg = RagAgentSettings.from_env()
    if not cfg.api_key:
        raise RagAgentError("RAG_AGENT_API_KEY not configured")
    try:
        response = _session.post(
            cfg.base_url + "/query",
            headers={"X-API-Key": cfg.api_key},
            json={"question": question, "top_k": top_k},
            timeout=cfg.timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RagAgentError(f"rag-agent unreachable: {exc}") from exc
    if response.status_code != 200:
        raise RagAgentError(f"rag-agent HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise RagAgentError("rag-agent returned non-JSON") from exc
    return RagAgentResult(
        answer=str(data.get("answer", "")).strip(),
        sources=list(data.get("citations") or []),
        refused=bool(data.get("refused")),
    )


def upload_document_to_rag_agent(filename: str, content: bytes,
                                 content_type: str = "text/markdown",
                                 visibility: str = "private") -> dict:
    """把文件转发到 rag-agent /documents/upload（blog 租户隔离知识）。

    返回 rag-agent 的响应 dict（含 document_id/status）。
    失败抛 RagAgentError，由调用方决定提示方式。
    """
    cfg = RagAgentSettings.from_env()
    if not cfg.api_key:
        raise RagAgentError("RAG_AGENT_API_KEY not configured")
    try:
        response = _session.post(
            cfg.base_url + "/documents/upload",
            headers={"X-API-Key": cfg.api_key},
            files={"file": (filename, content, content_type or "application/octet-stream")},
            data={"visibility": visibility, "source": "blog-upload"},
            timeout=cfg.timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RagAgentError(f"rag-agent unreachable: {exc}") from exc
    if response.status_code != 200:
        raise RagAgentError(f"rag-agent HTTP {response.status_code}: {response.text[:120]}")
    try:
        return response.json()
    except ValueError as exc:
        raise RagAgentError("rag-agent returned non-JSON") from exc


def answer_via_rag_agent(question: str) -> BlogAgentAnswer:
    """rag-agent 结果 → BlogAgentAnswer 同构；citations 转为展示用 sources。"""
    result = query_rag_agent(question)
    # 必须用 BlogAgentSource dataclass：to_dict() 对 sources 做 dataclasses.asdict
    sources = [
        BlogAgentSource(
            title=str(c.get("citation") or f"rag-agent 引用 {c.get('n', i + 1)}"),
            kind="rag-agent",
            content=str(c.get("citation") or ""),
            score=0.0,
            url="",
            document_id=None,
            chunk_index=c.get("n"),
        )
        for i, c in enumerate(result.sources)
    ]
    trace = [
        f"rag_agent -> HTTP 200, refused={result.refused}, citations={len(result.sources)}",
    ]
    if result.refused:
        return BlogAgentAnswer(
            answer=result.answer or "知识库中未找到足够依据回答此问题。",
            sources=[],
            trace=[*trace, "rag_agent -> refused"],
            token_usage=empty_token_usage(),
        )
    return BlogAgentAnswer(
        answer=result.answer,
        sources=sources,
        trace=trace,
        token_usage=empty_token_usage(),
    )
