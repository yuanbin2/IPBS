"""Preview a local HTML file as Markdown without persisting its original bytes."""

import uuid

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import jwt_user_from_request

from ..exceptions import ErrorCode
from ..models import UserProfile
from ..services.blog_media import validate_blog_image
from ..services.html_import import MAX_HTML_BYTES, HtmlImportError, convert_html_to_markdown
from ..services.remote_blog_image import RemoteImageError, fetch_remote_image
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


class BlogHtmlImportImageFetchView(APIView):
    """Localize one explicitly selected remote image before a draft is changed."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        user = jwt_user_from_request(request)
        if user is None:
            return error_response("请先登录后再导入图片", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        if not UserProfile.objects.filter(
            user=user, role__in=[UserProfile.Role.OPERATOR, UserProfile.Role.ADMIN]
        ).exists():
            return error_response("没有导入远程图片的权限", ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN)
        try:
            key = f"blog-html-image-fetch-hour:{user.pk}"
            count = 1 if cache.add(key, 1, timeout=3600) else cache.incr(key)
            if count > 20:
                return error_response(
                    "远程图片导入过于频繁，请稍后再试", ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS
                )
        except (RedisError, ConnectionError, OSError):
            return error_response(
                "导入限流服务暂不可用", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE
            )
        if not isinstance(request.data, dict):
            return error_response("图片地址无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        raw_url = request.data.get("url", "")
        if not isinstance(raw_url, str):
            return error_response("图片地址无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        try:
            data, suffix = fetch_remote_image(raw_url)
        except RemoteImageError as exc:
            code = ErrorCode.VALIDATION_ERROR if exc.http_status in {400, 413} else ErrorCode.UPSTREAM_UNAVAILABLE
            return error_response(str(exc), code, exc.http_status)

        storage = storages["blog_media"]
        stored_name = None
        try:
            stored_name = storage.save(f"blog/{uuid.uuid4().hex}{suffix}", ContentFile(data))
            filename = stored_name.rsplit("/", 1)[-1]
            with storage.open(stored_name, "rb") as stored_file:
                validate_blog_image(stored_file, filename)
        except Exception:
            if stored_name:
                try:
                    storage.delete(stored_name)
                except Exception:
                    pass
            return error_response(
                "图片存储或读回失败，请稍后重试", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE
            )
        return Response({"url": f"/media/blog/{filename}"}, status=status.HTTP_201_CREATED)
