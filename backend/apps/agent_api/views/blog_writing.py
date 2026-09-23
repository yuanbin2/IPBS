"""博客写作助手：为已登录作者生成 Markdown 建议。"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import context_from_request

from ..exceptions import ErrorCode
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

        mode = str(request.data.get("mode", "task_list")).strip()
        if mode not in WRITING_MODES:
            return error_response(
                "mode must be one of: task_list, outline, draft, improve",
                ErrorCode.VALIDATION_ERROR,
                status.HTTP_400_BAD_REQUEST,
            )

        instruction = str(request.data.get("instruction", "")).strip()[:2000]
        raw_draft = request.data.get("draft") or {}
        if not isinstance(raw_draft, dict):
            return error_response("draft must be an object", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)

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
            }
        )
