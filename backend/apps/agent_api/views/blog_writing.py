"""博客写作助手：为已登录作者生成 Markdown 建议。"""

import json

from django.core.cache import cache
from django.utils import timezone
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import context_from_request, get_or_create_profile, jwt_user_from_request, normalize_workspace_key

from ..exceptions import ErrorCode
from ..models import PrivateNote
from ..services.writing_agent import WRITING_MODES, BlogWritingAgent, WritingAgentConfigurationError
from .common import error_response


class BlogWritingAgentView(APIView):
    """Generate Markdown suggestions for an authenticated blog author."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        context = context_from_request(request)
        if not context.authenticated:
            return error_response(
                "请先登录后再使用写作助手。", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED
            )
        if not isinstance(request.data, dict):
            return error_response("请求必须是 JSON 对象", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)

        mode = str(request.data.get("mode", "task_list")).strip()
        if mode not in WRITING_MODES:
            return error_response(
                "mode must be one of: task_list, outline, draft, improve, note_summary",
                ErrorCode.VALIDATION_ERROR,
                status.HTTP_400_BAD_REQUEST,
            )

        instruction = str(request.data.get("instruction", "")).strip()[:2000]
        sources = []
        truncated = False
        if mode == "note_summary":
            user = jwt_user_from_request(request)
            if user is None:
                return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
            note_ids = request.data.get("note_ids")
            if (
                not isinstance(note_ids, list)
                or not 1 <= len(note_ids) <= 10
                or any(type(note_id) is not int or note_id < 1 for note_id in note_ids)
                or len(set(note_ids)) != len(note_ids)
            ):
                return error_response(
                    "请选择 1～10 条不同的笔记", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
                )
            workspace_key = normalize_workspace_key(get_or_create_profile(user).workspace_key)
            found = PrivateNote.objects.filter(
                pk__in=note_ids, owner=user, workspace_key=workspace_key, deleted_at__isnull=True
            )
            notes_by_id = {note.id: note for note in found}
            if len(notes_by_id) != len(note_ids):
                return error_response("笔记不存在或无权访问", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
            per_note_limit = min(4000, 16000 // len(note_ids))
            blocks = []
            for note_id in note_ids:
                note = notes_by_id[note_id]
                if not note.quote.strip() and not note.content.strip():
                    return error_response(
                        "所选笔记没有可汇总的内容", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
                    )
                text = f"摘录：{note.quote}\n内容：{note.content}".strip()
                included = text[:per_note_limit]
                is_truncated = len(text) > per_note_limit
                truncated = truncated or is_truncated
                sources.append(
                    {
                        "note_id": note.id,
                        "title": note.title,
                        "included_chars": len(included),
                        "truncated": is_truncated,
                    }
                )
                blocks.append(
                    f"[笔记#{note.id}] 标题：{json.dumps(note.title, ensure_ascii=False)}\n"
                    f"数据：{json.dumps(included, ensure_ascii=False)}"
                )
            draft = {"title": "私人笔记汇总", "summary": "", "category": "", "tags": "", "content": "\n\n".join(blocks)}
        else:
            draft = None
        raw_draft = request.data.get("draft") or {}
        if draft is None and not isinstance(raw_draft, dict):
            return error_response("draft must be an object", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)

        if draft is None:
            draft = {
                "title": str(raw_draft.get("title", "")).strip()[:300],
                "summary": str(raw_draft.get("summary", "")).strip()[:1200],
                "category": str(raw_draft.get("category", "")).strip()[:120],
                "tags": str(raw_draft.get("tags", "")).strip()[:500],
                "content": str(raw_draft.get("content", ""))[:16000],
            }
        if not instruction and not draft["title"] and not draft["content"].strip():
            return error_response(
                "请填写写作要求、文章标题或正文后再生成。", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )

        if mode == "note_summary":
            rate_key = f"blog-note-summary-hour:{user.pk}"
            try:
                if cache.add(rate_key, 1, timeout=3600):
                    recent_count = 1
                else:
                    try:
                        recent_count = cache.incr(rate_key)
                    except ValueError:
                        cache.add(rate_key, 1, timeout=3600)
                        recent_count = 1
            except RedisError:
                return error_response(
                    "笔记汇总暂不可用，请稍后再试", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE
                )
            if recent_count > 10:
                return error_response(
                    "笔记汇总太频繁，请稍后再试", ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS
                )

        try:
            result = BlogWritingAgent().generate(mode=mode, instruction=instruction, draft=draft)
        except WritingAgentConfigurationError as exc:
            return error_response(str(exc), ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception:
            return error_response(
                "写作助手生成失败，请稍后重试或检查模型配置。", ErrorCode.INTERNAL_ERROR, status.HTTP_502_BAD_GATEWAY
            )

        return Response(
            {
                "markdown": result.markdown,
                "mode": result.mode,
                "model": result.model,
                "api_key_source": result.api_key_source,
                **(
                    {
                        "sources": sources,
                        "truncated": truncated,
                        "generated_at": timezone.now().isoformat(),
                    }
                    if mode == "note_summary"
                    else {}
                ),
            }
        )
