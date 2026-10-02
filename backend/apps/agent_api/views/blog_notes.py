"""Owner-only private notes. Notes never enter article approval or public RAG."""

import math

from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import get_or_create_profile, jwt_user_from_request, normalize_workspace_key

from ..exceptions import ErrorCode
from ..models import BlogArticle, PrivateNote
from .common import error_response


def note_principal(request):
    user = jwt_user_from_request(request)
    if user is None:
        return None
    profile = get_or_create_profile(user)
    return user, normalize_workspace_key(profile.workspace_key)


def note_query(principal, *, include_deleted=False):
    user, workspace_key = principal
    notes = PrivateNote.objects.filter(owner=user, workspace_key=workspace_key)
    return notes if include_deleted else notes.filter(deleted_at__isnull=True)


def serialize_note(note):
    return {
        "id": note.pk,
        "title": note.title,
        "content": note.content,
        "quote": note.quote,
        "anchor_offset": note.anchor_offset,
        "source_article": note.source_article_id,
        "source_article_slug": note.source_article.slug if note.source_article_id else None,
        "version": note.version,
        "deleted_at": note.deleted_at.isoformat() if note.deleted_at else None,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }


def parse_note_fields(data, principal, *, partial=False):
    fields = {}
    limits = {"title": 180, "content": 50_000, "quote": 2_000}
    for field, limit in limits.items():
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, str) or len(value) > limit:
            return None, f"{field} 格式或长度无效"
        fields[field] = value.strip() if field == "title" else value
    if "anchor_offset" in data:
        raw_offset = data["anchor_offset"]
        if raw_offset is None:
            fields["anchor_offset"] = None
        elif isinstance(raw_offset, bool) or not isinstance(raw_offset, int) or not 0 <= raw_offset <= 10_000_000:
            return None, "高亮位置无效"
        else:
            fields["anchor_offset"] = raw_offset
    if not partial and not fields.get("title"):
        return None, "笔记标题不能为空"
    if partial and "title" in fields and not fields["title"]:
        return None, "笔记标题不能为空"
    if "source_article" in data:
        raw_id = data["source_article"]
        if raw_id is None:
            fields["source_article"] = None
        else:
            try:
                article_id = int(raw_id)
            except (TypeError, ValueError):
                return None, "来源文章无效"
            user, workspace_key = principal
            article = BlogArticle.objects.filter(pk=article_id, workspace_key=workspace_key).first()
            if article is None or (
                article.status != BlogArticle.Status.PUBLISHED and article.author_name != user.username
            ):
                return None, "来源文章不可访问"
            fields["source_article"] = article
    return fields, None


class PrivateNoteListCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        principal = note_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 20))
        except (ValueError, TypeError):
            return error_response("页码无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        if not 1 <= page <= 10000 or not 1 <= page_size <= 50:
            return error_response("页码或每页数量超出范围", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        query = str(request.query_params.get("q", "")).strip()
        if len(query) > 100:
            return error_response("关键词过长", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        deleted = str(request.query_params.get("deleted", "")) == "1"
        notes = note_query(principal, include_deleted=deleted).select_related("source_article")
        if "source_article" in request.query_params:
            try:
                article_id = int(request.query_params["source_article"])
            except (TypeError, ValueError):
                return error_response("来源文章无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
            if article_id < 1:
                return error_response("来源文章无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
            notes = notes.filter(source_article_id=article_id)
        if deleted:
            notes = notes.filter(deleted_at__isnull=False)
        if query:
            notes = notes.filter(Q(title__icontains=query) | Q(content__icontains=query) | Q(quote__icontains=query))
        total = notes.count()
        start = (page - 1) * page_size
        return Response(
            {
                "items": [serialize_note(note) for note in notes[start : start + page_size]],
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": math.ceil(total / page_size),
            }
        )

    def post(self, request):
        principal = note_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        fields, error = parse_note_fields(request.data, principal)
        if error:
            return error_response(error, ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        user, workspace_key = principal
        note = PrivateNote.objects.create(owner=user, workspace_key=workspace_key, **fields)
        return Response(serialize_note(note), status=status.HTTP_201_CREATED)


class PrivateNoteDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, note_id):
        principal = note_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        note = get_object_or_404(note_query(principal).select_related("source_article"), pk=note_id)
        return Response(serialize_note(note))

    def put(self, request, note_id):
        principal = note_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        note = get_object_or_404(note_query(principal), pk=note_id)
        fields, error = parse_note_fields(request.data, principal, partial=True)
        if error:
            return error_response(error, ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        if not fields:
            return error_response("没有可更新内容", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        try:
            version = int(request.data.get("version"))
        except (ValueError, TypeError):
            return error_response("需要笔记版本", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        updated = (
            note_query(principal)
            .filter(pk=note.pk, version=version)
            .update(**fields, version=F("version") + 1, updated_at=timezone.now())
        )
        if not updated:
            return error_response(
                "笔记已在其他位置更新，请刷新后重试", ErrorCode.VALIDATION_ERROR, status.HTTP_409_CONFLICT
            )
        note.refresh_from_db()
        return Response(serialize_note(note))

    def delete(self, request, note_id):
        principal = note_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        note = get_object_or_404(note_query(principal), pk=note_id)
        now = timezone.now()
        PrivateNote.objects.filter(pk=note.pk, deleted_at__isnull=True).update(
            deleted_at=now, version=F("version") + 1, updated_at=now
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PrivateNoteRestoreView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, note_id):
        principal = note_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        note = get_object_or_404(
            note_query(principal, include_deleted=True).select_related("source_article"), pk=note_id
        )
        if note.deleted_at is None:
            return error_response("笔记未删除", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        PrivateNote.objects.filter(pk=note.pk, deleted_at__isnull=False).update(
            deleted_at=None, version=F("version") + 1, updated_at=now
        )
        note.refresh_from_db()
        return Response(serialize_note(note))
