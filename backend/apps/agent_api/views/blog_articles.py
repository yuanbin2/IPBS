"""博客文章资源：列表/创建、详情/编辑、发布审批、相关文章与图片上传。"""

import math
import uuid
import warnings
from io import BytesIO
from pathlib import Path

from botocore.exceptions import ClientError
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import context_from_request

from ..exceptions import ErrorCode
from ..models import ApprovalRequest, BlogArticle, BlogArticleRevision, UserProfile
from ..serializers import serialize_approval_request, serialize_article
from ..services.blog import (
    ArticleAccessError,
    ArticleListFilters,
    article_publication_fingerprint,
    fill_default_cover,
    filtered_articles,
    get_or_create_category,
    list_articles,
    set_article_tags,
    unique_slug,
)
from ..services.blog_media import is_blog_image_name, validate_blog_image
from .common import approval_required_response, error_response, get_workspace_key, require_roles


class BlogArticleListCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        context = context_from_request(request)
        filters = ArticleListFilters(
            status=request.query_params.get("status", BlogArticle.Status.PUBLISHED),
            category_slug=str(request.query_params.get("category", "")).strip(),
            tag_slug=str(request.query_params.get("tag", "")).strip(),
            query=str(request.query_params.get("q", "")).strip(),
            author_name=str(request.query_params.get("author_name", "")).strip(),
            my_only=str(request.query_params.get("my", "")).strip() == "1",
        )
        try:
            articles = list_articles(
                filters,
                workspace_key=get_workspace_key(request),
                actor=context.actor,
                authenticated=context.authenticated,
                is_admin=context.authenticated and context.role in {UserProfile.Role.ADMIN, UserProfile.Role.OPERATOR},
            )
        except ArticleAccessError as exc:
            return error_response(str(exc), ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        return Response([serialize_article(article) for article in articles])

    def post(self, request):
        title = str(request.data.get("title", "")).strip()
        content = str(request.data.get("content", "")).strip()
        if not title or not content:
            return error_response(
                "title and content are required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST
            )

        context = context_from_request(request)

        # 已登录用户使用用户名，未登录用户使用提交的 author_name
        if context.authenticated:
            author_name = context.actor
        else:
            author_name = str(request.data.get("author_name", "")).strip()
            if not author_name:
                return error_response("请先登录或填写昵称", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)

        article = BlogArticle.objects.create(
            title=title,
            workspace_key=get_workspace_key(request),
            slug=unique_slug(BlogArticle, request.data.get("slug") or title, max_length=200),
            author_name=author_name,
            summary=str(request.data.get("summary", "")).strip(),
            cover_image=str(request.data.get("cover_image", "")).strip(),
            content=content,
            category=get_or_create_category(request.data.get("category")),
            status=BlogArticle.Status.DRAFT,
        )
        set_article_tags(article, request.data.get("tags", []))
        # 没填封面就用正文第一张图片，避免列表/卡片没有配图。
        if fill_default_cover(article):
            article.save(update_fields=["cover_image", "updated_at"])

        # All submissions go through approval
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
            workspace_key=get_workspace_key(request),
            title=f"发布博客：{article.title}",
            description=f"{'用户 ' + author_name + ' 提交的' if context.authenticated else '访客 ' + author_name + ' 提交的'}博客文章，发布后会公开；仅在选择加入知识库时写入知识库。",
            payload={
                "article_slug": article.slug,
                "article_id": article.id,
                "title": article.title,
                "author_name": author_name,
                "add_to_knowledge_base": request.data.get("add_to_knowledge_base") is True,
                "article_fingerprint": article_publication_fingerprint(article),
            },
            requester=author_name,
        )
        return Response(
            {
                "approval_required": True,
                "article": serialize_article(article, include_content=True),
                "approval": serialize_approval_request(approval),
                "detail": "文章已保存为草稿，发布请求已进入人工审批。",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class BlogArticleDiscoverView(APIView):
    """Stable, bounded discovery for the public library and an author's own posts."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        context = context_from_request(request)
        raw_status = str(request.query_params.get("status", BlogArticle.Status.PUBLISHED)).strip()
        if raw_status not in {
            BlogArticle.Status.PUBLISHED,
            BlogArticle.Status.DRAFT,
            BlogArticle.Status.REJECTED,
            "all",
        }:
            return error_response("状态筛选无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        try:
            page = int(request.query_params.get("page", 1))
            from ..models import BlogSetting

            default_page_size = BlogSetting.load().articles_per_page or 12
            page_size = int(request.query_params.get("page_size", default_page_size))
        except (TypeError, ValueError):
            return error_response("页码无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        if page < 1 or page > 10000 or page_size < 1 or page_size > 24:
            return error_response("页码或每页数量超出范围", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        query = str(request.query_params.get("q", "")).strip()
        if len(query) > 100:
            return error_response("关键词过长", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        my_only = str(request.query_params.get("my", "")).strip() == "1"
        if my_only and not context.authenticated:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        filters = ArticleListFilters(
            status=raw_status,
            category_slug=str(request.query_params.get("category", "")).strip(),
            tag_slug=str(request.query_params.get("tag", "")).strip(),
            query=query,
            my_only=my_only,
        )
        try:
            articles = filtered_articles(
                filters,
                workspace_key=get_workspace_key(request),
                actor=context.actor,
                authenticated=context.authenticated,
                is_admin=context.authenticated and context.role in {UserProfile.Role.ADMIN, UserProfile.Role.OPERATOR},
            )
        except ArticleAccessError as exc:
            return error_response(str(exc), ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        if my_only:
            articles = articles.filter(author_name__iexact=context.actor)
        articles = articles.order_by("-published_at", "-created_at", "-id")
        total = articles.count()
        first = (page - 1) * page_size
        items = articles[first : first + page_size]
        return Response(
            {
                "items": [serialize_article(article) for article in items],
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": math.ceil(total / page_size),
            }
        )


class BlogImageUploadView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        upload = request.FILES.get("image")
        if upload is None:
            return error_response("image is required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)

        declared_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
        if not declared_type.startswith("image/"):
            return error_response(
                "only image files are supported", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )

        max_size = 5 * 1024 * 1024
        if upload.size > max_size:
            return error_response(
                "image must be smaller than 5MB", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )

        image_data = upload.read()
        if len(image_data) > max_size:
            return error_response(
                "image must be smaller than 5MB", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )

        supported_formats = {
            "PNG": ("image/png", ".png"),
            "JPEG": ("image/jpeg", ".jpg"),
            "GIF": ("image/gif", ".gif"),
            "WEBP": ("image/webp", ".webp"),
        }
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(image_data)) as image:
                    detected = supported_formats.get(image.format)
                    if (
                        detected is None
                        or image.width * image.height > 20_000_000
                        or getattr(image, "n_frames", 1) > 100
                    ):
                        raise ValueError("unsupported image or image dimensions")
                    image.verify()

                # verify() checks the container; load() also forces every frame to decode.
                with Image.open(BytesIO(image_data)) as image:
                    decoded_pixels = 0
                    for frame_index in range(getattr(image, "n_frames", 1)):
                        image.seek(frame_index)
                        frame_pixels = image.width * image.height
                        if frame_pixels > 20_000_000:
                            raise ValueError("image frame is too large")
                        decoded_pixels += frame_pixels
                        if decoded_pixels > 40_000_000:
                            raise ValueError("too many decoded pixels")
                        image.load()
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            EOFError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ):
            return error_response("invalid or oversized image", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)

        if declared_type != detected[0]:
            return error_response(
                "unsupported or mismatched image format", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )

        _, suffix = detected
        storage = storages["blog_media"]
        stored_name = storage.save(
            f"blog/{uuid.uuid4().hex}{suffix}",
            ContentFile(image_data),
        )
        filename = stored_name.rsplit("/", 1)[-1]
        image_url = f"/media/blog/{filename}"
        alt_text = Path(upload.name).stem.replace("[", "").replace("]", "").replace("\n", " ").strip()
        return Response(
            {
                "url": image_url,
                "markdown": f"![{alt_text}]({image_url})",
            },
            status=status.HTTP_201_CREATED,
        )


class BlogImageReadView(APIView):
    """Public proxy for explicitly public blog images; private files use other routes."""

    authentication_classes = []
    permission_classes = []

    def get(self, request, filename: str):
        try:
            # A flat, generated filename allowlist prevents arbitrary storage keys
            # and keeps every request inside the blog/ public-image namespace.
            if not is_blog_image_name(filename) or "/" in filename or "\\" in filename:
                raise ValueError("invalid image key")
            storage_file = storages["blog_media"].open(f"blog/{filename}", "rb")
            _, content_type = validate_blog_image(storage_file, filename)
        except (FileNotFoundError, OSError, ValueError, Image.DecompressionBombError, Http404):
            raise Http404 from None
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                raise Http404 from None
            raise

        response = FileResponse(storage_file, content_type=content_type)
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


class BlogArticleDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, slug: str):
        context = context_from_request(request)
        article = get_object_or_404(
            BlogArticle.objects.select_related("category", "knowledge_document").prefetch_related("tags"),
            slug=slug,
            workspace_key=get_workspace_key(request),
        )
        can_read_private = context.authenticated and (
            context.role in {UserProfile.Role.ADMIN, UserProfile.Role.OPERATOR}
            or article.author_name.casefold() == context.actor.casefold()
        )
        if article.status != BlogArticle.Status.PUBLISHED and not can_read_private:
            raise Http404
        if article.status == BlogArticle.Status.PUBLISHED:
            BlogArticle.objects.filter(pk=article.pk).update(view_count=F("view_count") + 1)
            article.refresh_from_db(fields=["view_count"])
        payload = serialize_article(
            article,
            include_content=True,
            include_comments=request.query_params.get("include_comments") != "0",
        )
        if can_read_private and article.status == BlogArticle.Status.PUBLISHED:
            pending = article.revisions.filter(status=BlogArticleRevision.Status.PENDING).first()
            if pending:
                payload["pending_revision"] = {
                    "id": pending.id,
                    "base_version": pending.base_version,
                    "title": pending.title,
                    "summary": pending.summary,
                    "cover_image": pending.cover_image,
                    "content": pending.content,
                    "category": pending.category.name if pending.category else "",
                    "tags": pending.tags,
                }
        return Response(payload)

    @transaction.atomic
    def put(self, request, slug: str):
        """Save a private draft or queue a published article revision for review."""
        article = get_object_or_404(
            BlogArticle.objects.select_for_update(), slug=slug, workspace_key=get_workspace_key(request)
        )

        # Check if user is admin/operator
        context = context_from_request(request)
        is_admin = context.authenticated and context.role in {UserProfile.Role.ADMIN, UserProfile.Role.OPERATOR}

        # 必须登录才能编辑
        if not context.authenticated:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)

        # 普通用户只能编辑自己的文章（忽略大小写）
        if not is_admin and article.author_name.lower() != context.actor.lower():
            return error_response("只能编辑自己提交的文章", ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN)

        title = str(request.data.get("title", article.title)).strip()
        content = str(request.data.get("content", article.content)).strip()
        if not title or not content or len(title) > 180:
            return error_response("标题或正文无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)

        if article.status == BlogArticle.Status.PUBLISHED:
            try:
                expected_version = int(request.data.get("publication_version"))
            except (TypeError, ValueError):
                return error_response("缺少公开版本号，请刷新文章后重试", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT)
            if expected_version != article.publication_version:
                return error_response("公开版本已变化，请刷新并核对修改", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT)
            raw_tags = request.data.get("tags", [tag.name for tag in article.tags.all()])
            if not isinstance(raw_tags, list):
                return error_response("标签格式无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
            category = (
                get_or_create_category(request.data.get("category")) if "category" in request.data else article.category
            )
            revision = BlogArticleRevision.objects.create(
                article=article,
                base_version=article.publication_version,
                title=title,
                summary=str(request.data.get("summary", article.summary)).strip(),
                cover_image=str(request.data.get("cover_image", article.cover_image)).strip(),
                content=content,
                category=category,
                tags=[str(tag).strip() for tag in raw_tags if str(tag).strip()],
                submitted_by=context.actor,
            )
            if fill_default_cover(revision):
                revision.save(update_fields=["cover_image"])
            BlogArticleRevision.objects.filter(article=article, status=BlogArticleRevision.Status.PENDING).exclude(
                pk=revision.pk
            ).update(status=BlogArticleRevision.Status.SUPERSEDED, reviewed_at=timezone.now())
            ApprovalRequest.objects.filter(
                action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
                payload__article_slug=article.slug,
                status=ApprovalRequest.Status.PENDING,
                workspace_key=article.workspace_key,
            ).update(status=ApprovalRequest.Status.REJECTED, result="文章修订已被新版本替代。")
            approval = ApprovalRequest.objects.create(
                action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
                workspace_key=article.workspace_key,
                title=f"发布博客修订：{title}",
                description=f"用户 {context.actor} 提交公开文章修订；审核前旧版本保持公开。",
                payload={
                    "article_slug": article.slug,
                    "article_id": article.id,
                    "revision_id": revision.id,
                    "base_version": revision.base_version,
                    "title": title,
                    "add_to_knowledge_base": request.data.get("add_to_knowledge_base") is True,
                },
                requester=context.actor,
            )
            return Response(
                {
                    "approval_required": True,
                    "article": serialize_article(article, include_content=True),
                    "revision_id": revision.id,
                    "approval": serialize_approval_request(approval),
                    "detail": "修订已提交审核，原文章在审核期间继续公开。",
                },
                status=status.HTTP_202_ACCEPTED,
            )

        # Update article fields
        article.title = title
        if "summary" in request.data:
            article.summary = str(request.data["summary"]).strip()
        if "cover_image" in request.data:
            article.cover_image = str(request.data["cover_image"]).strip()
        article.content = content
        if "category" in request.data:
            article.category = get_or_create_category(request.data.get("category"))
        # 只有显式传了空字符串才算"清空封面"；否则用正文首图兜底。
        if "cover_image" in request.data and not article.cover_image.strip():
            fill_default_cover(article)

        article.save()

        if "tags" in request.data:
            set_article_tags(article, request.data.get("tags", []))

        # Cancel any existing pending approval for this article
        ApprovalRequest.objects.filter(
            action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
            payload__article_slug=article.slug,
            status=ApprovalRequest.Status.PENDING,
            workspace_key=get_workspace_key(request),
        ).update(status=ApprovalRequest.Status.REJECTED, result="用户更新了文章内容，此审批已被替代。")

        # Create a new approval request
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
            workspace_key=get_workspace_key(request),
            title=f"发布博客：{article.title}",
            description=f"用户 {context.actor} 更新了博客文章，发布后会公开；仅在选择加入知识库时写入知识库。",
            payload={
                "article_slug": article.slug,
                "article_id": article.id,
                "title": article.title,
                "author_name": context.actor,
                "add_to_knowledge_base": request.data.get("add_to_knowledge_base") is True,
                "article_fingerprint": article_publication_fingerprint(article),
            },
            requester=context.actor,
        )

        return Response(
            {
                "approval_required": True,
                "article": serialize_article(article, include_content=True),
                "approval": serialize_approval_request(approval),
                "detail": "文章已更新，等待管理员审核后会公开发布。",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @transaction.atomic
    def patch(self, request, slug: str):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        article = get_object_or_404(
            BlogArticle.objects.select_for_update(), slug=slug, workspace_key=get_workspace_key(request)
        )
        if article.status == BlogArticle.Status.PUBLISHED:
            return error_response(
                "已发布文章请通过带公开版本号的 PUT 提交修订",
                ErrorCode.CONFLICT,
                status.HTTP_409_CONFLICT,
            )
        if "title" in request.data:
            article.title = str(request.data["title"]).strip()
        if "summary" in request.data:
            article.summary = str(request.data["summary"]).strip()
        if "cover_image" in request.data:
            article.cover_image = str(request.data["cover_image"]).strip()
        if "content" in request.data:
            article.content = str(request.data["content"]).strip()
        if "category" in request.data:
            article.category = get_or_create_category(request.data.get("category"))
        if "status" in request.data:
            requested_status = str(request.data["status"])
            if requested_status not in {BlogArticle.Status.DRAFT, BlogArticle.Status.ARCHIVED}:
                return error_response("状态修改无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
            article.status = requested_status
        if request.data.get("publish"):
            fill_default_cover(article)
        article.save()
        if "tags" in request.data:
            set_article_tags(article, request.data.get("tags", []))
        if set(request.data) & {"title", "summary", "cover_image", "content", "category", "tags", "status", "publish"}:
            ApprovalRequest.objects.filter(
                action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
                payload__article_slug=article.slug,
                status=ApprovalRequest.Status.PENDING,
                workspace_key=article.workspace_key,
            ).update(status=ApprovalRequest.Status.REJECTED, result="文章内容或发布请求已变化，请重新提交审批。")
        if article.status == BlogArticle.Status.PUBLISHED or request.data.get("publish"):
            article.status = BlogArticle.Status.DRAFT
            article.save(update_fields=["status", "updated_at"])
            approval = ApprovalRequest.objects.create(
                action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
                workspace_key=get_workspace_key(request),
                title=f"发布博客：{article.title}",
                description="发布博客会公开文章；仅在选择加入知识库时写入知识库。",
                payload={
                    "article_slug": article.slug,
                    "article_id": article.id,
                    "title": article.title,
                    "add_to_knowledge_base": request.data.get("add_to_knowledge_base") is True,
                    "article_fingerprint": article_publication_fingerprint(article),
                },
                requester=str(request.data.get("requester", "blog-editor")).strip(),
            )
            return Response(
                {
                    "approval_required": True,
                    "article": serialize_article(article, include_content=True),
                    "approval": serialize_approval_request(approval),
                    "detail": "发布请求已进入人工审批。",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        return Response(serialize_article(article, include_content=True))

    @transaction.atomic
    def delete(self, request, slug: str):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.DELETE_BLOG_ARTICLE,
            workspace_key=get_workspace_key(request),
            title=f"删除博客：{article.title}",
            description="批准后删除文章及同步的知识库文档；仅清理未被其他内容引用的博客图片。",
            payload={"article_slug": article.slug, "article_id": article.id, "title": article.title},
            requester=(
                str(request.data.get("requester", "blog-editor")).strip() if hasattr(request, "data") else "blog-editor"
            ),
        )
        return approval_required_response(approval)


class BlogArticlePublishView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, slug: str):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))
        # 发布兜底：没填封面时用正文第一张图片，审核页与公开卡片都有配图。
        if fill_default_cover(article):
            article.save(update_fields=["cover_image", "updated_at"])
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
            workspace_key=get_workspace_key(request),
            title=f"发布博客：{article.title}",
            description="发布博客会公开文章；仅在选择加入知识库时写入知识库。",
            payload={
                "article_slug": article.slug,
                "article_id": article.id,
                "title": article.title,
                "add_to_knowledge_base": request.data.get("add_to_knowledge_base") is True,
                "article_fingerprint": article_publication_fingerprint(article),
            },
            requester=(
                str(request.data.get("requester", "blog-editor")).strip() if hasattr(request, "data") else "blog-editor"
            ),
        )
        return approval_required_response(approval)


class BlogArticleRelatedView(APIView):
    """Return related articles based on category and tag overlap."""

    authentication_classes = []
    permission_classes = []

    def get(self, request, slug: str):
        article = get_object_or_404(
            BlogArticle.objects.select_related("category").prefetch_related("tags"),
            slug=slug,
            workspace_key=get_workspace_key(request),
            status=BlogArticle.Status.PUBLISHED,
        )

        article_tag_ids = set(article.tags.values_list("id", flat=True))
        category_id = article.category_id

        candidates = (
            BlogArticle.objects.filter(
                status=BlogArticle.Status.PUBLISHED,
                workspace_key=get_workspace_key(request),
            )
            .exclude(pk=article.pk)
            .select_related("category")
            .prefetch_related("tags")
        )

        scored = []
        for candidate in candidates:
            score = 0
            if category_id and candidate.category_id == category_id:
                score += 10
            candidate_tag_ids = set(candidate.tags.values_list("id", flat=True))
            overlap = article_tag_ids & candidate_tag_ids
            score += len(overlap) * 3
            if candidate.view_count > 0:
                score += min(5, math.log10(candidate.view_count))
            if score > 0:
                scored.append((score, candidate))

        scored.sort(key=lambda x: x[0], reverse=True)
        related = [serialize_article(c) for _, c in scored[:6]]
        return Response(related)
