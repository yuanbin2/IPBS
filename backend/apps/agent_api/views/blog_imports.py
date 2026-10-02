"""Preview a local HTML file as Markdown without persisting its original bytes."""

from django.core.cache import cache
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import jwt_user_from_request

from ..exceptions import ErrorCode
from ..services.html_import import MAX_HTML_BYTES, HtmlImportError, convert_html_to_markdown
from .common import error_response


class BlogHtmlImportPreviewView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        user = jwt_user_from_request(request)
        if user is None:
            return error_response("请先登录后再导入网页", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        if (
            request.META.get("CONTENT_LENGTH", "").isdigit()
            and int(request.META["CONTENT_LENGTH"]) > MAX_HTML_BYTES + 65536
        ):
            return error_response(
                "HTML 文件不能超过 5 MiB", ErrorCode.VALIDATION_ERROR, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )
        try:
            key = f"blog-html-import-hour:{user.pk}"
            if cache.add(key, 1, timeout=3600):
                count = 1
            else:
                count = cache.incr(key)
            if count > 30:
                return error_response(
                    "网页导入过于频繁，请稍后再试", ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS
                )
        except (RedisError, ConnectionError, OSError):
            return error_response(
                "导入限流服务暂不可用", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE
            )

        upload = request.FILES.get("file")
        if upload is None:
            return error_response("请选择 HTML 文件", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)
        if upload.size > MAX_HTML_BYTES:
            return error_response(
                "HTML 文件不能超过 5 MiB", ErrorCode.VALIDATION_ERROR, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )
        data = upload.read(MAX_HTML_BYTES + 1)
        if len(data) > MAX_HTML_BYTES:
            return error_response(
                "HTML 文件不能超过 5 MiB", ErrorCode.VALIDATION_ERROR, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )
        try:
            result = convert_html_to_markdown(
                data,
                filename=upload.name,
                source_url=str(request.data.get("source_url", "")),
                mode=str(request.data.get("mode", "article")),
            )
        except HtmlImportError as exc:
            return error_response(str(exc), ErrorCode.VALIDATION_ERROR, exc.http_status)
        return Response(result)
