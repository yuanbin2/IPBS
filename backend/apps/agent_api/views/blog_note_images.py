"""B-043 私有笔记配图：非公开存储、owner/workspace 鉴权读取、过期清理。

绝不以 /media/... 公开地址暴露：读取必须携带登录态，且只允许本人
同 workspace 访问。失败时保留草稿，不把外链伪报为“已保存为私有图片”。
"""

import hashlib
import logging
import mimetypes
import os
import uuid
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import jwt_user_from_request

from ..exceptions import ErrorCode
from ..models import PrivateNote, PrivateNoteImage
from ..services.blog_media import validate_blog_image
from ..services.remote_blog_image import RemoteImageError, fetch_remote_image
from .common import error_response

PRIVATE_NOTE_IMAGE_MAX_BYTES = 5 * 1024 * 1024
PRIVATE_NOTE_IMAGE_HOURLY_LIMIT = 60
# 未被任何笔记引用、且创建超过该时长的临时图片可被清理
ORPHAN_TTL_HOURS = 24
logger = logging.getLogger(__name__)


def _ensure_dir(storage) -> None:
    """FileSystemStorage 不会自动创建 location，先确保目录存在。"""
    location = getattr(storage, "location", None)
    if not location:
        return
    try:
        os.makedirs(str(location), exist_ok=True)
    except OSError:
        pass


def private_note_storage():
    """私有图片存放在独立 storages 别名，绝不落在公开 media 根下。"""
    return storages["private_note_media"]


def image_principal(request):
    user = jwt_user_from_request(request)
    if user is None:
        return None
    return user


def serialize_private_image(image, request):
    return {
        "id": image.pk,
        "url": f"/api/agent/blog/notes/images/{image.pk}/",
        "original_name": image.original_name,
        "byte_size": image.byte_size,
        "source_url": image.source_url,
        "bound_to_note": image.note_id,
        "created_at": image.created_at.isoformat(),
        "requires_auth": True,
    }


def _rate_limited(user) -> Response | None:
    from django.core.cache import cache
    from redis.exceptions import RedisError

    try:
        key = f"blog-private-image-hour:{user.pk}"
        count = 1 if cache.add(key, 1, timeout=3600) else cache.incr(key)
        if count > PRIVATE_NOTE_IMAGE_HOURLY_LIMIT:
            return error_response(
                "私有图片操作过于频繁，请稍后再试", ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS
            )
    except (RedisError, ConnectionError, OSError):
        return error_response("图片服务暂不可用", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE)
    return None


class PrivateNoteImageUploadView(APIView):
    """POST /blog/notes/images/ —— 上传本地图片为私有附件。"""

    authentication_classes = []
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        user = image_principal(request)
        if user is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        denied = _rate_limited(user)
        if denied:
            return denied
        upload = request.FILES.get("image")
        if upload is None:
            return error_response("请选择图片文件", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)
        if upload.size > PRIVATE_NOTE_IMAGE_MAX_BYTES:
            return error_response(
                "私有图片不能超过 5 MiB", ErrorCode.VALIDATION_ERROR, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )
        data = upload.read(PRIVATE_NOTE_IMAGE_MAX_BYTES + 1)
        if len(data) > PRIVATE_NOTE_IMAGE_MAX_BYTES:
            return error_response(
                "私有图片不能超过 5 MiB", ErrorCode.VALIDATION_ERROR, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )
        from agent.security import get_or_create_profile

        profile = get_or_create_profile(user)
        _ensure_dir(private_note_storage())
        try:
            suffix = Path(upload.name).suffix.lower() or ".png"
            stored_name = f"{user.pk}/{uuid.uuid4().hex}{suffix}"
            private_note_storage().save(stored_name, ContentFile(data))
        except Exception:
            return error_response(
                "图片存储失败，请稍后重试", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE
            )
        image = PrivateNoteImage.objects.create(
            owner=user,
            workspace_key=profile.workspace_key,
            file=stored_name,
            original_name=upload.name[:200],
            byte_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        # 读回校验：失败则删除，避免出现存不回去的孤儿对象
        try:
            with private_note_storage().open(stored_name, "rb") as stored:
                validate_blog_image(stored, Path(stored.name).name)
        except Exception:
            private_note_storage().delete(stored_name)
            image.delete()
            return error_response(
                "图片读回校验失败，文件未保存", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )
        return Response(serialize_private_image(image, request), status=status.HTTP_201_CREATED)


class PrivateNoteImageFetchView(APIView):
    """POST /blog/notes/images/fetch/ —— 由服务端抓取剪藏里的远程图片。

    复用既有远程图片防护（DNS/连接 IP/重定向/类型/大小）；成功后落入私有存储，
    失败时不改草稿、不把外链当成本地图片。
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        user = image_principal(request)
        if user is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        denied = _rate_limited(user)
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return error_response("请求体必须是 JSON 对象", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        raw_url = request.data.get("url")
        if not isinstance(raw_url, str) or not raw_url.strip():
            return error_response("图片地址无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        from agent.security import get_or_create_profile

        profile = get_or_create_profile(user)
        try:
            data, suffix = fetch_remote_image(raw_url)
        except RemoteImageError as exc:
            code = ErrorCode.VALIDATION_ERROR if exc.http_status in {400, 413} else ErrorCode.UPSTREAM_UNAVAILABLE
            return error_response(str(exc), code, exc.http_status)
        _ensure_dir(private_note_storage())
        try:
            stored_name = f"{user.pk}/{uuid.uuid4().hex}{suffix}"
            private_note_storage().save(stored_name, ContentFile(data))
        except Exception:
            return error_response(
                "图片存储失败，请稍后重试", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE
            )
        image = PrivateNoteImage.objects.create(
            owner=user,
            workspace_key=profile.workspace_key,
            file=stored_name,
            original_name=raw_url.rsplit("/", 1)[-1][:200],
            source_url=raw_url[:2048],
            byte_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        try:
            with private_note_storage().open(stored_name, "rb") as stored:
                validate_blog_image(stored, Path(stored.name).name)
        except Exception:
            private_note_storage().delete(stored_name)
            image.delete()
            return error_response(
                "图片读回校验失败，文件未保存", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )
        return Response(serialize_private_image(image, request), status=status.HTTP_201_CREATED)


class PrivateNoteImageReadView(APIView):
    """GET /blog/notes/images/<id>/ —— 认证读回（绝无公开地址）。"""

    authentication_classes = []
    permission_classes = []

    def get(self, request, image_id: int):
        user = jwt_user_from_request(request)
        if user is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        from agent.security import get_or_create_profile

        profile = get_or_create_profile(user)
        image = PrivateNoteImage.objects.filter(pk=image_id, owner=user, workspace_key=profile.workspace_key).first()
        if image is None:
            # 跨用户/跨 workspace 一律 404，不暴露对象是否存在
            return error_response("图片不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        try:
            handle = private_note_storage().open(image.file.name, "rb")
        except Exception:
            return error_response("图片读取失败", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        mime_type = mimetypes.guess_type(image.file.name)[0] or "application/octet-stream"
        response = FileResponse(handle, content_type=mime_type)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class PrivateNoteImageBindView(APIView):
    """POST /blog/notes/<id>/images/bind/ —— 保存笔记时把临时图片挂到笔记上。"""

    authentication_classes = []
    permission_classes = []

    @transaction.atomic
    def post(self, request, note_id: int):
        user = jwt_user_from_request(request)
        if user is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        from agent.security import get_or_create_profile

        profile = get_or_create_profile(user)
        note = PrivateNote.objects.filter(
            pk=note_id, owner=user, workspace_key=profile.workspace_key, deleted_at__isnull=True
        ).first()
        if note is None:
            return error_response("笔记不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        raw_ids = request.data.get("image_ids") if isinstance(request.data, dict) else None
        if not isinstance(raw_ids, list):
            return error_response("image_ids 必须是数组", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        bound = 0
        for raw_id in raw_ids:
            try:
                image_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            updated = PrivateNoteImage.objects.filter(
                pk=image_id, owner=user, workspace_key=profile.workspace_key
            ).update(note=note)
            bound += updated
        return Response({"bound": bound})


def cleanup_orphan_private_images(*, apply: bool = False) -> int:
    """Preview expired unbound images by default; delete only on explicit apply."""
    cutoff = timezone.now() - timezone.timedelta(hours=ORPHAN_TTL_HOURS)
    orphans = PrivateNoteImage.objects.filter(note__isnull=True, created_at__lt=cutoff)
    if not apply:
        return orphans.count()
    removed = 0
    for image in orphans:
        with transaction.atomic():
            current = (
                PrivateNoteImage.objects.select_for_update()
                .filter(pk=image.pk, note__isnull=True, created_at__lt=cutoff)
                .first()
            )
            if current is None:
                continue
            try:
                storage = private_note_storage()
                storage.delete(current.file.name)
                if storage.exists(current.file.name):
                    raise OSError("object_still_exists")
            except Exception as exc:
                # Keep the row so the failure remains visible and retryable.
                logger.warning("private_orphan_cleanup_failed image_id=%s error=%s", current.pk, type(exc).__name__)
                continue
            current.delete()
            removed += 1
    return removed
