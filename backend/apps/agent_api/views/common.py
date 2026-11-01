import hashlib
import os
import re
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

try:
    # agent 模块缺失时的部署降级：只兜底 common 自身需要的名字，
    # 其他模块按约定直接从 agent.* 导入。
    from agent.multi_agent import MultiAgentSupervisor
    from agent.security import (
        context_from_request,
        role_allowed,
        security_enforced,
    )
except ImportError:
    MultiAgentSupervisor = None
    context_from_request = None
    role_allowed = None
    security_enforced = None

from ..exceptions import ErrorCode
from ..models import (
    AgentObservation,
    AgentRun,
    ApprovalRequest,
    BlogArticle,
    BlogArticleRevision,
    BlogCollection,
    Conversation,
    ConversationProject,
    Document,
    EvaluationCase,
    KnowledgeBase,
    MCPTool,
    SecurityAuditEvent,
)
from ..serializers import serialize_approval_request
from ..services.blog import (
    article_publication_fingerprint,
    fill_default_cover,
    publish_article_to_knowledge_base,
    set_article_tags,
)
from ..services.blog_image_cleanup import article_image_names, delete_unreferenced_blog_images
from ..services.evaluation import SCORER_VERSION

DEFAULT_MESSAGE_LIMIT = 30


MAX_MESSAGE_LIMIT = 50


BLOG_AGENT_RATE_LIMIT = 12


BLOG_AGENT_RATE_WINDOW_SECONDS = 60


def get_workspace_key(request) -> str:
    return context_from_request(request).workspace_key


def get_conversation_owner(request) -> str:
    """Return the stable identity used to isolate private chat history."""
    return context_from_request(request).actor or "anonymous"


def get_or_create_conversation(
    conversation_id,
    message: str,
    workspace_key: str,
    owner_username: str,
    project_id=None,
) -> Conversation:
    """按 id 取会话（带 workspace/owner 校验，不能跨用户复用），缺省则创建。

    新建时可指定 project_id，让对话直接落入所选项目；项目校验失败时
    退化为未分组，不影响对话本身。
    """
    if conversation_id:
        return get_object_or_404(
            Conversation,
            pk=conversation_id,
            workspace_key=workspace_key,
            owner_username=owner_username,
        )

    title = message[:40]
    if len(message) > 40:
        title = f"{title}..."
    project = None
    if project_id:
        project = ConversationProject.objects.filter(
            pk=project_id,
            workspace_key=workspace_key,
            owner_username=owner_username,
        ).first()
    return Conversation.objects.create(
        title=title,
        workspace_key=workspace_key,
        owner_username=owner_username,
        project=project,
    )


def error_response(detail: str, code: str, http_status: int, **extra) -> Response:
    """统一错误响应：detail 给人看，code 给前端做程序化分支（见 exceptions.py）。"""
    return Response({"detail": detail, "code": code, **extra}, status=http_status)


def audit_security_event(
    request,
    event_type: str,
    detail: str = "",
    metadata: dict | None = None,
    *,
    actor: str | None = None,
    role: str | None = None,
    workspace_key: str | None = None,
) -> None:
    context = context_from_request(request)
    SecurityAuditEvent.objects.create(
        event_type=event_type,
        actor=actor or context.actor,
        role=role or context.role,
        workspace_key=workspace_key or context.workspace_key,
        path=request.path[:240],
        detail=detail,
        metadata=metadata or {},
    )


def require_roles(request, allowed_roles: list[str]) -> Response | None:
    context = context_from_request(request)
    if not security_enforced():
        return None
    if context.authenticated and role_allowed(context.role, allowed_roles):
        return None
    audit_security_event(
        request,
        SecurityAuditEvent.EventType.ACCESS_DENIED,
        f"required roles: {', '.join(allowed_roles)}",
    )
    return error_response(
        "permission denied",
        ErrorCode.FORBIDDEN,
        status.HTTP_403_FORBIDDEN,
        required_roles=allowed_roles,
        current_role=context.role,
    )


def serialize_security_context(request) -> dict:
    context = context_from_request(request)
    return {
        "actor": context.actor,
        "role": context.role,
        "workspace_key": context.workspace_key,
        "authenticated": context.authenticated,
        "security_enforced": security_enforced(),
    }


def get_message_limit(request) -> int:
    try:
        limit = int(request.query_params.get("limit", DEFAULT_MESSAGE_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_MESSAGE_LIMIT
    return max(1, min(limit, MAX_MESSAGE_LIMIT))


def request_ip_hash(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded_for.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    if not ip:
        return ""
    return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()


DEFAULT_MCP_TOOLS = [
    {
        "name": "local_file_search",
        "display_name": "本地文件搜索",
        "description": "在根目录 README 与 docs/ 下全部 Markdown 说明文档中按关键词检索（含设计、API、数据库与缺陷跟踪文档），返回「文件:行号」便于定位；不含源码与知识库。",
        "category": MCPTool.Category.FILESYSTEM,
        "permission_scope": "read:project_public_files",
        "is_enabled": True,
    },
    {
        "name": "git_repo_info",
        "display_name": "Git 仓库信息",
        "description": "读取当前分支、最近提交和工作区状态。",
        "category": MCPTool.Category.GIT,
        "permission_scope": "read:git_metadata",
        "is_enabled": True,
    },
    {
        "name": "web_search",
        "display_name": "网页搜索",
        "description": "外部网页搜索工具占位，默认关闭。",
        "category": MCPTool.Category.WEB,
        "permission_scope": "network:web_search",
        "is_enabled": False,
    },
    {
        "name": "safe_database_stats",
        "display_name": "安全数据库统计",
        "description": "只返回业务聚合指标，不暴露表结构和敏感字段。",
        "category": MCPTool.Category.DATABASE,
        "permission_scope": "read:aggregate_stats",
        "is_enabled": True,
    },
]


def ensure_default_mcp_tools() -> None:
    for tool in DEFAULT_MCP_TOOLS:
        MCPTool.objects.get_or_create(name=tool["name"], defaults=tool)


def env_file_is_git_tracked() -> bool:
    env_path = Path(settings.BASE_DIR).parent / ".env"
    git_index = Path(settings.BASE_DIR).parent / ".git" / "index"
    if not env_path.exists() or not git_index.exists():
        return False
    try:
        import subprocess

        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".env"],
            cwd=Path(settings.BASE_DIR).parent,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def selected_agent_from_response(response_data: dict) -> str:
    supervisor = response_data.get("supervisor") or {}
    return str(supervisor.get("selected_agent") or "")


def tool_call_succeeded(call: dict) -> bool:
    """判断单次工具调用是否成功。

    优先读 ToolResult 序列化出的显式 `ok` 标志；历史数据没有该字段时
    回退到输出关键词判断（旧数据的近似值）。
    """
    if "ok" in call:
        return bool(call["ok"])
    output = str(call.get("output", "")).lower()
    return bool(output) and not any(marker in output for marker in ["error", "failed", "异常", "失败"])


def calculate_tool_success_rate(tool_calls: list[dict]) -> float:
    if not tool_calls:
        return 1.0
    successful = sum(1 for call in tool_calls if tool_call_succeeded(call))
    return round(successful / len(tool_calls), 2)


def evaluate_answer(case: EvaluationCase, response_data: dict, observation: AgentObservation) -> dict:
    """Score only against explicitly human-reviewed, auditable annotations.

    Answer pattern matching is a deterministic rubric, not a semantic judge. Citation
    support is established only by the reviewed fact→source mapping plus an inline
    [1]-style citation on the same answer sentence. Unmapped claims stay unknown.
    """
    scorer_version = SCORER_VERSION
    answer = str(response_data.get("answer", ""))
    selected_agent = selected_agent_from_response(response_data)
    annotation = case.annotation if isinstance(case.annotation, dict) else {}
    reviewed = (
        annotation.get("schema_version") == 1
        and annotation.get("review_status") == "human_reviewed"
        and bool(annotation.get("reviewer"))
        and bool(annotation.get("reviewed_at"))
    )
    null_metric = {
        "score": None,
        "numerator": None,
        "denominator": None,
        "status": "undetermined",
        "reason": "缺少经人工审核的标注",
    }

    def result(score, denominator, status_value="scored", reason=""):
        return {
            "score": round(score, 4) if score is not None else None,
            "numerator": None if score is None else round(score * denominator),
            "denominator": denominator,
            "status": status_value,
            "reason": reason,
        }

    if not reviewed:
        correctness = faithfulness = citation_accuracy = citation_coverage = refusal_quality = null_metric.copy()
        evaluation_status = "needs_review"
        evidence_trace = []
    else:
        facts = annotation.get("atomic_facts", [])
        forbidden = annotation.get("forbidden_claims", [])
        sources = response_data.get("sources", []) if isinstance(response_data.get("sources", []), list) else []
        source_ids = [
            str(item.get("chunk_id") or item.get("source_id") or item.get("id") or "")
            for item in sources
            if isinstance(item, dict)
        ]
        source_content = {
            str(item.get("chunk_id") or item.get("source_id") or item.get("id") or ""): str(item.get("content") or "")
            for item in sources
            if isinstance(item, dict)
        }
        lines = [line.strip() for line in re.split(r"[\n。！？.!?]+", answer) if line.strip()]
        cited_refs = re.findall(r"\[(\d+)\]", answer)
        valid_citation_markers = set()
        cited_total = len(cited_refs)
        expected_count = len(facts)
        covered_count = 0
        mapped_claim_count = 0
        supported_count = 0
        required_citation_count = sum(1 for fact in facts if fact.get("requires_citation", True))
        trace = []
        for fact in facts:
            patterns = [str(p) for p in fact.get("answer_patterns", []) if p]
            matched = next(
                ((line_index, line) for line_index, line in enumerate(lines) if any(p in line for p in patterns)),
                None,
            )
            if not matched:
                trace.append(
                    {"fact_id": fact.get("id"), "answer_match": False, "cited_source_ids": [], "support": "missing"}
                )
                continue
            line_index, matched_line = matched
            covered_count += 1
            mapped_claim_count += 1
            required_sources = [str(s) for s in fact.get("allowed_source_ids", [])]
            support_patterns = [str(p) for p in fact.get("support_patterns", []) if p]
            requires_citation = bool(fact.get("requires_citation", True))
            refs = re.findall(r"\[(\d+)\]", matched_line)
            ref_matches = list(re.finditer(r"\[(\d+)\]", matched_line))
            cited_ids = [
                source_ids[int(ref.group(1)) - 1] for ref in ref_matches if 1 <= int(ref.group(1)) <= len(source_ids)
            ]
            visible_support_ids = [
                source_id
                for source_id in required_sources
                if source_id in source_content
                and any(pattern in source_content[source_id] for pattern in support_patterns)
            ]
            cited_support_ids = [source_id for source_id in cited_ids if source_id in visible_support_ids]
            citation_supports_fact = bool(cited_support_ids)
            visible_evidence_supports_fact = bool(visible_support_ids)
            for ref_match in ref_matches:
                source_index = int(ref_match.group(1)) - 1
                if not 0 <= source_index < len(source_ids):
                    continue
                source_id = source_ids[source_index]
                if source_id in required_sources and any(
                    pattern in source_content.get(source_id, "") for pattern in support_patterns
                ):
                    # One citation marker can support multiple annotated facts, but it
                    # remains one citation for citation-accuracy's numerator.
                    valid_citation_markers.add((line_index, ref_match.start()))
            faithfulness_supported = citation_supports_fact if requires_citation else visible_evidence_supports_fact
            if faithfulness_supported:
                supported_count += 1
            trace.append(
                {
                    "fact_id": fact.get("id"),
                    "answer_match": True,
                    "cited_source_ids": cited_ids,
                    "visible_support_source_ids": visible_support_ids,
                    "inline_citation_support": citation_supports_fact,
                    "support": (
                        "supported"
                        if faithfulness_supported
                        else (
                            "citation_required"
                            if visible_evidence_supports_fact and requires_citation and not refs
                            else ("unsupported" if refs else "missing")
                        )
                    ),
                }
            )
        forbidden_hit = any(
            any(str(p) and str(p) in answer for p in item.get("match_phrases", [])) for item in forbidden
        )
        # This rubric cannot discover arbitrary natural-language claims. Require an
        # explicit annotation assertion that all answer claims are mapped before scoring faithfulness.
        claims_reviewed = annotation.get("claim_review_complete") is True
        allowed_non_factual = {re.sub(r"\s+", "", str(p)) for p in annotation.get("non_factual_patterns", []) if p}
        refusal_patterns_for_mapping = [str(p) for p in annotation.get("refusal_patterns", []) if p]

        def line_has_only_reviewed_content(line):
            if re.sub(r"\s+", "", line) in allowed_non_factual:
                return True
            patterns = [
                str(pattern)
                for fact in facts
                for pattern in fact.get("answer_patterns", [])
                if pattern and str(pattern) in line
            ]
            patterns.extend(pattern for pattern in refusal_patterns_for_mapping if pattern in line)
            residual = line
            for pattern in patterns:
                residual = residual.replace(pattern, "", 1)
            residual = re.sub(r"\[\d+\]", "", residual)
            residual = re.sub(r"[\s，、,.!！？:：;；()（）\[\]]+", "", residual)
            return not residual

        unmapped_lines = [line for line in lines if not line_has_only_reviewed_content(line)]
        if unmapped_lines:
            trace.append({"unmapped_response_lines": unmapped_lines, "support": "needs_review"})
        correctness = result(
            (
                0.0
                if forbidden_hit
                else (
                    covered_count / expected_count
                    if expected_count
                    else (1.0 if annotation.get("should_refuse") else None)
                )
            ),
            expected_count or (1 if annotation.get("should_refuse") else 0),
            "scored" if expected_count or annotation.get("should_refuse") else "not_applicable",
            "命中禁止主张" if forbidden_hit else ("" if expected_count else "没有标注原子事实"),
        )
        faithfulness = result(
            (
                supported_count / mapped_claim_count
                if mapped_claim_count and claims_reviewed and not unmapped_lines
                else (1.0 if not expected_count and claims_reviewed and annotation.get("should_refuse") else None)
            ),
            mapped_claim_count,
            (
                "scored"
                if mapped_claim_count and claims_reviewed and not unmapped_lines
                else (
                    "not_applicable"
                    if not mapped_claim_count and annotation.get("should_refuse") and not unmapped_lines
                    else "undetermined"
                )
            ),
            (
                "回答包含未映射句子或主张"
                if unmapped_lines
                else ("回答主张未完成逐项人工映射" if not claims_reviewed else "")
            ),
        )
        citation_accuracy = result(
            len(valid_citation_markers) / cited_total if cited_total else (0.0 if required_citation_count else None),
            cited_total,
            ("scored" if cited_total or required_citation_count else "not_applicable"),
            "无引用但题目要求证据" if not cited_total and required_citation_count else "",
        )
        citation_coverage = result(
            (
                sum(
                    1
                    for row in trace
                    if row["support"] == "supported"
                    and next((f.get("requires_citation", True) for f in facts if f.get("id") == row["fact_id"]), True)
                )
                / required_citation_count
                if required_citation_count
                else None
            ),
            required_citation_count,
            ("scored" if required_citation_count else "not_applicable"),
            "没有需要引用的标注事实" if not required_citation_count else "",
        )
        should_refuse = annotation.get("should_refuse") is True
        refusal_patterns = [str(p) for p in annotation.get("refusal_patterns", []) if p]
        if should_refuse:
            refuses = (
                any(pattern in answer for pattern in refusal_patterns) and not forbidden_hit and not unmapped_lines
            )
            refusal_quality = result(1.0 if refuses else 0.0, 1, reason="")
        else:
            refusal_quality = {"score": None, "status": "not_applicable", "reason": "该题不要求拒答"}
        evidence_trace = trace
        metric_statuses = [
            m["status"]
            for m in (correctness, faithfulness, citation_accuracy, citation_coverage)
            if m.get("status") != "not_applicable"
        ]
        evaluation_status = "needs_review" if "undetermined" in metric_statuses else "scored"
        if should_refuse and refusal_quality["score"] is None:
            evaluation_status = "needs_review"

    return {
        "scorer_version": scorer_version,
        "evaluation_status": evaluation_status,
        "answer_correctness": correctness,
        "faithfulness": faithfulness,
        "citation_accuracy": citation_accuracy,
        "citation_coverage": citation_coverage,
        "refusal_quality": refusal_quality,
        "evidence_trace": evidence_trace,
        "latency_ms": observation.latency_ms,
        "tool_success_rate": observation.tool_success_rate,
        "runtime_metrics": {
            "latency_ms": observation.latency_ms,
            "tool_success_rate": observation.tool_success_rate,
            "token_usage": response_data.get("token_usage", {}),
        },
        "selected_agent": selected_agent,
        "expected_agent": case.expected_agent,
    }


def create_agent_observation(
    *,
    conversation: Conversation | None,
    agent_run: AgentRun | None,
    input_message: str,
    workspace_key: str = "default",
    response_data: dict | None = None,
    latency_ms: int = 0,
    failure_reason: str = "",
) -> AgentObservation:
    response_data = response_data or {}
    tool_calls = response_data.get("tool_calls", [])
    return AgentObservation.objects.create(
        conversation=conversation,
        agent_run=agent_run,
        input_message=input_message,
        workspace_key=workspace_key,
        answer=str(response_data.get("answer", "")),
        route=str(response_data.get("route", "")),
        selected_agent=selected_agent_from_response(response_data),
        trace=response_data.get("trace", []),
        tool_calls=tool_calls,
        sources=response_data.get("sources", []),
        token_usage=response_data.get("token_usage", {}),
        latency_ms=latency_ms,
        tool_success_rate=calculate_tool_success_rate(tool_calls),
        status=AgentObservation.Status.FAILED if failure_reason else AgentObservation.Status.SUCCESS,
        failure_reason=failure_reason,
        langsmith_project=os.environ.get("LANGSMITH_PROJECT", ""),
        langsmith_run_id=str(response_data.get("langsmith_run_id", "")),
    )


def observability_summary(workspace_key: str | None = None) -> dict:
    observations = AgentObservation.objects.all()
    if workspace_key:
        observations = observations.filter(workspace_key=workspace_key)
    total = observations.count()
    if total == 0:
        return {
            "total_runs": 0,
            "success_rate": 1.0,
            "average_latency_ms": 0,
            "average_tool_success_rate": 1.0,
            "failed_runs": 0,
            "langsmith_enabled": bool(os.environ.get("LANGSMITH_API_KEY")),
            "langsmith_project": os.environ.get("LANGSMITH_PROJECT", ""),
        }

    successful = observations.filter(status=AgentObservation.Status.SUCCESS).count()
    latency_sum = sum(item.latency_ms for item in observations[:200])
    tool_rate_sum = sum(item.tool_success_rate for item in observations[:200])
    sample_count = min(total, 200)
    return {
        "total_runs": total,
        "success_rate": round(successful / total, 2),
        "average_latency_ms": round(latency_sum / sample_count),
        "average_tool_success_rate": round(tool_rate_sum / sample_count, 2),
        "failed_runs": total - successful,
        "langsmith_enabled": bool(os.environ.get("LANGSMITH_API_KEY")),
        "langsmith_project": os.environ.get("LANGSMITH_PROJECT", ""),
    }


def approval_required_response(approval: ApprovalRequest) -> Response:
    return Response(
        {
            "approval_required": True,
            "detail": "该操作已进入人工审批队列，审批通过后才会执行。",
            "approval": serialize_approval_request(approval),
        },
        status=status.HTTP_202_ACCEPTED,
    )


def extract_blog_delete_target(message: str) -> str:
    if not any(keyword in message for keyword in ["删除文章", "删除博客", "删掉文章", "删掉博客"]):
        return ""
    quoted = re.search(r"[《「\"]([^》」\"]+)[》」\"]", message)
    if quoted:
        return quoted.group(1).strip()
    cleaned = re.sub(r"(请|帮我|删除|删掉|文章|博客|这篇|一下|吧|。|，|,)", " ", message)
    return re.sub(r"\s+", " ", cleaned).strip()


def maybe_create_blog_delete_approval(message: str, request) -> ApprovalRequest | None:
    target = extract_blog_delete_target(message)
    if not target:
        return None
    article = (
        BlogArticle.objects.filter(workspace_key=get_workspace_key(request), title__icontains=target)
        .order_by("-updated_at")
        .first()
    )
    if not article:
        article = (
            BlogArticle.objects.filter(workspace_key=get_workspace_key(request), slug__icontains=target)
            .order_by("-updated_at")
            .first()
        )
    if not article:
        return None
    return ApprovalRequest.objects.create(
        action=ApprovalRequest.Action.DELETE_BLOG_ARTICLE,
        workspace_key=get_workspace_key(request),
        title=f"删除博客：{article.title}",
        description="对话触发的删除博客请求；管理员审批后删除文章和对应知识库文档，并清理不再被引用的博客图片。",
        payload={"article_slug": article.slug, "article_id": article.id, "title": article.title},
        requester=(
            str(request.data.get("requester", "chat-agent")).strip() if hasattr(request, "data") else "chat-agent"
        ),
    )


def maybe_create_mcp_approval(message: str, request) -> ApprovalRequest | None:
    if not MultiAgentSupervisor.is_mcp_request(message):
        return None
    tool_name = MultiAgentSupervisor.select_mcp_tool_name(message)
    tool = MCPTool.objects.filter(
        name=tool_name,
        workspace_key=get_workspace_key(request),
        is_enabled=True,
        requires_approval=True,
    ).first()
    if not tool:
        return None
    return ApprovalRequest.objects.create(
        action=ApprovalRequest.Action.EXECUTE_MCP_TOOL,
        workspace_key=get_workspace_key(request),
        title=f"执行 MCP 工具：{tool.display_name}",
        description=f"聊天请求调用工具；权限范围：{tool.permission_scope}",
        payload={"tool_id": tool.id, "tool_name": tool.name, "query": message},
        requester=serialize_security_context(request)["actor"],
    )


def execute_approval_request(approval: ApprovalRequest) -> str:
    payload = approval.payload or {}

    if approval.action == ApprovalRequest.Action.DELETE_DOCUMENT:
        document = get_object_or_404(Document, pk=payload.get("document_id"), workspace_key=approval.workspace_key)
        title = document.title
        if document.source_file:
            document.source_file.delete(save=False)
        document.delete()
        return f"文档已删除：{title}"

    if approval.action == ApprovalRequest.Action.DELETE_KNOWLEDGE_BASE:
        knowledge_base = get_object_or_404(
            KnowledgeBase, pk=payload.get("knowledge_base_id"), workspace_key=approval.workspace_key
        )
        name = knowledge_base.name
        knowledge_base.delete()
        return f"知识库已删除：{name}"

    if approval.action == ApprovalRequest.Action.DELETE_BLOG_ARTICLE:
        article = get_object_or_404(BlogArticle, slug=payload.get("article_slug"), workspace_key=approval.workspace_key)
        title = article.title
        image_names = article_image_names(article)
        knowledge_document = article.knowledge_document
        article.delete()
        if knowledge_document:
            if knowledge_document.source_file:
                knowledge_document.source_file.delete(save=False)
            knowledge_document.delete()
        # Storage cannot join the DB transaction. Only remove files after commit,
        # and only when no article, revision, note, or other content still uses them.
        transaction.on_commit(lambda: delete_unreferenced_blog_images(image_names))
        return f"博客文章已删除：{title}"

    if approval.action == ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE:
        with transaction.atomic():
            article = get_object_or_404(
                BlogArticle.objects.select_for_update(),
                slug=payload.get("article_slug"),
                workspace_key=approval.workspace_key,
            )
            revision_id = payload.get("revision_id")
            if revision_id is None:
                expected_fingerprint = payload.get("article_fingerprint")
                if expected_fingerprint:
                    if article_publication_fingerprint(article) != expected_fingerprint:
                        raise ValueError("文章内容已变化，请重新提交发布审批")
                elif article.updated_at > approval.created_at:
                    # Older pending approvals predate fingerprints. They can only
                    # proceed if no API save has occurred since their creation.
                    raise ValueError("文章内容可能已变化，请重新提交发布审批")
            if revision_id is not None:
                revision = get_object_or_404(
                    BlogArticleRevision.objects.select_for_update(), pk=revision_id, article=article
                )
                if revision.status != BlogArticleRevision.Status.PENDING:
                    raise ValueError("文章修订已失效")
                if article.publication_version != revision.base_version:
                    raise ValueError("公开版本已变化，修订需要重新提交")
                article.title = revision.title
                article.summary = revision.summary
                article.cover_image = revision.cover_image
                article.content = revision.content
                article.category = revision.category
                article.save(update_fields=["title", "summary", "cover_image", "content", "category", "updated_at"])
                set_article_tags(article, revision.tags)
            # 发布兜底：封面为空时用正文第一张图片（修订版同样适用）。
            if fill_default_cover(article):
                article.save(update_fields=["cover_image", "updated_at"])
            was_published = article.status == BlogArticle.Status.PUBLISHED
            sync_knowledge = payload.get("add_to_knowledge_base") is True or bool(article.knowledge_document_id)
            if sync_knowledge:
                publish_article_to_knowledge_base(article)
            else:
                article.status = BlogArticle.Status.PUBLISHED
                if article.published_at is None:
                    article.published_at = timezone.now()
                article.save(update_fields=["status", "published_at", "updated_at"])
            if revision_id is not None or not was_published:
                article.publication_version += 1
                article.save(update_fields=["publication_version", "updated_at"])
            if revision_id is not None:
                revision.status = BlogArticleRevision.Status.APPROVED
                revision.reviewed_at = timezone.now()
                revision.save(update_fields=["status", "reviewed_at"])
            if sync_knowledge:
                return f"博客文章已发布，知识库索引已提交后台处理：{article.title}"
            return f"博客文章已发布：{article.title}"

    if approval.action == ApprovalRequest.Action.PUBLISH_BLOG_COLLECTION:
        from ..services.blog_collections import snapshot_sha256

        with transaction.atomic():
            collection = get_object_or_404(
                BlogCollection.objects.select_for_update(),
                pk=payload.get("collection_id"),
                workspace_key=approval.workspace_key,
            )
            if collection.pending_approval_id != approval.pk:
                raise ValueError("目录待审已失效，需要作者重新提交")
            snapshot = collection.pending_snapshot
            if not snapshot:
                raise ValueError("待审快照缺失")
            if payload.get("snapshot_hash") != snapshot_sha256(snapshot):
                raise ValueError("待审快照校验失败")
            if payload.get("submit_version") != snapshot.get("draft_version"):
                raise ValueError("待审快照版本校验失败")
            collection.published_snapshot = snapshot
            collection.publication_version += 1
            collection.pending_snapshot = None
            collection.pending_approval = None
            collection.save(
                update_fields=[
                    "published_snapshot",
                    "publication_version",
                    "pending_snapshot",
                    "pending_approval",
                    "updated_at",
                ]
            )
            return f"领域目录已公开（第 {collection.publication_version} 版）：{collection.title}"

    if approval.action == ApprovalRequest.Action.EXECUTE_MCP_TOOL and payload.get("tool_name"):
        try:
            from agent.mcp_tools import LocalMCPToolRunner
        except ImportError:
            LocalMCPToolRunner = None

        tool = get_object_or_404(MCPTool, pk=payload.get("tool_id"), workspace_key=approval.workspace_key)
        if not tool.is_enabled:
            raise ValueError(f"MCP 工具已禁用：{tool.display_name}")
        execution = LocalMCPToolRunner(Path(settings.BASE_DIR).parent, workspace_key=approval.workspace_key).run(
            tool.name, str(payload.get("query", ""))
        )
        tool.last_used_at = timezone.now()
        tool.save(update_fields=["last_used_at", "updated_at"])
        return f"MCP 工具已执行：{tool.display_name}\n\n{execution.output}"

    return "该审批类型当前只记录审批结果，未绑定自动执行器。"
