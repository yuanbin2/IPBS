"""博客文章资源：列表/创建、详情/编辑、发布审批、相关文章与图片上传。"""

import math
from pathlib import Path

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import context_from_request

from ..exceptions import ErrorCode
from ..models import ApprovalRequest, BlogArticle, UserProfile
from ..serializers import serialize_approval_request, serialize_article
from ..services.blog import (
    ArticleAccessError,
    ArticleListFilters,
    get_or_create_category,
    list_articles,
    set_article_tags,
    unique_slug,
)
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

        # All submissions go through approval
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
            workspace_key=get_workspace_key(request),
            title=f"发布博客：{article.title}",
            description=f"{'用户 ' + author_name + ' 提交的' if context.authenticated else '访客 ' + author_name + ' 提交的'}博客文章，发布后会公开并写入知识库。",
            payload={
                "article_slug": article.slug,
                "article_id": article.id,
                "title": article.title,
                "author_name": author_name,
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

        if not upload.content_type.startswith("image/"):
            return error_response(
                "only image files are supported", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )

        suffix = Path(upload.name).suffix.lower() or ".png"
        if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}:
            return error_response("unsupported image format", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)

        max_size = 5 * 1024 * 1024
        if upload.size > max_size:
            return error_response(
                "image must be smaller than 5MB", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )

        import base64

        image_data = base64.b64encode(upload.read()).decode("utf-8")
        content_type = upload.content_type or "image/png"
        data_url = f"data:{content_type};base64,{image_data}"
        return Response(
            {
                "url": data_url,
                "markdown": f"![{Path(upload.name).stem}]({data_url})",
            },
            status=status.HTTP_201_CREATED,
        )


class BlogArticleDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, slug: str):
        article = get_object_or_404(
            BlogArticle.objects.select_related("category", "knowledge_document").prefetch_related("tags"),
            slug=slug,
            workspace_key=get_workspace_key(request),
        )
        article.view_count += 1
        article.save(update_fields=["view_count", "updated_at"])
        return Response(serialize_article(article, include_content=True))

    def put(self, request, slug: str):
        """Allow visitors to update their own articles (draft or published)."""
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))

        # Check if user is admin/operator
        context = context_from_request(request)
        is_admin = context.authenticated and context.role in {UserProfile.Role.ADMIN, UserProfile.Role.OPERATOR}

        # 必须登录才能编辑
        if not context.authenticated:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)

        # 普通用户只能编辑自己的文章（忽略大小写）
        if not is_admin and article.author_name.lower() != context.actor.lower():
            return error_response("只能编辑自己提交的文章", ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN)

        # Update article fields
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

        # If article was published, set it back to draft for re-approval
        if article.status == BlogArticle.Status.PUBLISHED:
            article.status = BlogArticle.Status.DRAFT
            article.published_at = None

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
            description=f"用户 {context.actor} 更新了博客文章，发布后会公开并写入知识库。",
            payload={
                "article_slug": article.slug,
                "article_id": article.id,
                "title": article.title,
                "author_name": context.actor,
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

    def patch(self, request, slug: str):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))
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
            article.status = str(request.data["status"])
        article.save()
        if "tags" in request.data:
            set_article_tags(article, request.data.get("tags", []))
        if article.status == BlogArticle.Status.PUBLISHED or request.data.get("publish"):
            article.status = BlogArticle.Status.DRAFT
            article.save(update_fields=["status", "updated_at"])
            approval = ApprovalRequest.objects.create(
                action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
                workspace_key=get_workspace_key(request),
                title=f"发布博客：{article.title}",
                description="发布博客会公开文章，并将文章内容写入知识库供 Agent 检索。",
                payload={"article_slug": article.slug, "article_id": article.id, "title": article.title},
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
            description="删除博客会移除文章，并删除它同步到知识库的文档。",
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
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
            workspace_key=get_workspace_key(request),
            title=f"发布博客：{article.title}",
            description="发布博客会公开文章，并将文章内容写入知识库供 Agent 检索。",
            payload={"article_slug": article.slug, "article_id": article.id, "title": article.title},
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
