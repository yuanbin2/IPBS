"""博客公开浏览端点：分类、标签、归档、关于与评论。"""

from hashlib import sha256

from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import context_from_request, jwt_user_from_request

from ..exceptions import ErrorCode
from ..models import (
    ArticleCategory,
    ArticleTag,
    BlogArticle,
    BlogComment,
    BlogCommentReport,
    SecurityAuditEvent,
    UserProfile,
)
from ..serializers import serialize_article, serialize_category, serialize_tag
from .blog_restrictions import active_restriction_for
from .common import error_response, get_workspace_key


class BlogCategoryListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        categories = ArticleCategory.objects.all()
        return Response([serialize_category(category) for category in categories])


class BlogTagListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        tags = ArticleTag.objects.all()
        return Response([serialize_tag(tag) for tag in tags])


class BlogArchiveView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        articles = BlogArticle.objects.filter(
            status=BlogArticle.Status.PUBLISHED,
            workspace_key=get_workspace_key(request),
        ).order_by("-published_at")
        archive: dict[str, list[dict]] = {}
        for article in articles:
            key = article.published_at.strftime("%Y-%m") if article.published_at else "未发布"
            archive.setdefault(key, []).append(serialize_article(article))
        return Response([{"month": month, "articles": items} for month, items in archive.items()])


class BlogAboutView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(
            {
                "title": "关于这个知识型博客",
                "content": (
                    "这个博客不是普通 CMS，而是个人技术经历和 Agent 知识库的入口。"
                    "文章发布后会自动进入知识库，访客不仅能阅读文章，也能向 Agent 询问项目经历、"
                    "架构思路、论文方向和技术栈选择。"
                ),
                "highlights": [
                    "Vue 3 + Django 的全栈项目",
                    "LangChain / LangGraph Agentic RAG",
                    "博客文章自动向量化并进入个人知识库",
                    "可交互的个人技术简历",
                ],
            }
        )


class BlogCommentCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, slug: str):
        article = get_object_or_404(
            BlogArticle,
            slug=slug,
            workspace_key=get_workspace_key(request),
            status=BlogArticle.Status.PUBLISHED,
        )
        comments = article.comments.filter(is_approved=True)
        if any(key in request.query_params for key in ("kind", "limit", "before_id")):
            kind = request.query_params.get("kind")
            if kind not in {"quote", "plain"}:
                return error_response(
                    "kind must be quote or plain", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
                )
            try:
                limit = int(request.query_params.get("limit", "20"))
                before_id = int(request.query_params["before_id"]) if "before_id" in request.query_params else None
            except (TypeError, ValueError):
                return error_response(
                    "invalid comment cursor or limit", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
                )
            if not 1 <= limit <= 50 or (before_id is not None and before_id <= 0):
                return error_response(
                    "invalid comment cursor or limit", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
                )
            comments = comments.exclude(quote="") if kind == "quote" else comments.filter(quote="")
            total = comments.count()
            if before_id is not None:
                comments = comments.filter(id__lt=before_id)
            page = list(comments.order_by("-id")[: limit + 1])
            has_more = len(page) > limit
            page = page[:limit]
            return Response(
                {
                    "items": [
                        {
                            "id": comment.id,
                            "author_name": comment.author_name,
                            "content": comment.content,
                            "quote": comment.quote,
                            "anchor_offset": comment.anchor_offset,
                            "created_at": comment.created_at.isoformat(),
                        }
                        for comment in page
                    ],
                    "total": total,
                    "next_before_id": page[-1].id if has_more else None,
                }
            )
        return Response(
            [
                {
                    "id": comment.id,
                    "author_name": comment.author_name,
                    "content": comment.content,
                    "quote": comment.quote,
                    "anchor_offset": comment.anchor_offset,
                    "created_at": comment.created_at.isoformat(),
                }
                for comment in comments
            ]
        )

    def post(self, request, slug: str):
        context = context_from_request(request)
        if not context.authenticated:
            return error_response("请先登录后评论", ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN)
        user = jwt_user_from_request(request)
        restriction = active_restriction_for(user, context.workspace_key) if user else None
        if restriction:
            return error_response(
                f"评论与举报功能已暂停至 {timezone.localtime(restriction.expires_at):%Y-%m-%d %H:%M}，可在博客页申诉。",
                ErrorCode.FORBIDDEN,
                status.HTTP_403_FORBIDDEN,
            )
        article = get_object_or_404(
            BlogArticle,
            slug=slug,
            workspace_key=get_workspace_key(request),
            status=BlogArticle.Status.PUBLISHED,
        )
        content = str(request.data.get("content", "")).strip()
        if not content:
            return error_response("content is required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)
        if len(content) > 2000:
            return error_response("comment is too long", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        quote = request.data.get("quote", "")
        if not isinstance(quote, str) or len(quote) > 2000:
            return error_response("摘录格式或长度无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        quote = quote.strip()
        anchor_offset = request.data.get("anchor_offset")
        if anchor_offset is not None and (
            isinstance(anchor_offset, bool)
            or not isinstance(anchor_offset, int)
            or not 0 <= anchor_offset <= 10_000_000
        ):
            return error_response("评论位置无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        if anchor_offset is not None and not quote:
            return error_response("需要选中的文字", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)

        identity = sha256(f"{context.workspace_key}\0{context.actor}".encode()).hexdigest()
        rate_key = f"blog-comment-minute:{identity}"
        try:
            if cache.add(rate_key, 1, timeout=60):
                recent_count = 1
            else:
                try:
                    recent_count = cache.incr(rate_key)
                except ValueError:
                    cache.add(rate_key, 1, timeout=60)
                    recent_count = 1
        except RedisError:
            return error_response(
                "评论暂不可用，请稍后再试", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE
            )
        if recent_count > 5:
            return error_response("评论太频繁，请稍后再试", ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS)

        comment = BlogComment.objects.create(
            article=article,
            author_name=context.actor[:80],
            content=content,
            quote=quote,
            anchor_offset=anchor_offset,
            is_approved=True,
        )
        return Response(
            {
                "id": comment.id,
                "author_name": comment.author_name,
                "moderation_status": "approved",
                "detail": "评论已公开。",
            },
            status=status.HTTP_201_CREATED,
        )


def _moderation_context(request):
    context = context_from_request(request)
    if not context.authenticated or context.role != UserProfile.Role.ADMIN:
        return None, error_response("permission denied", ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN)
    return context, None


class BlogCommentModerationListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        context, denied = _moderation_context(request)
        if denied:
            return denied
        review_state = str(request.query_params.get("status", "pending"))
        if review_state not in {"pending", "approved"}:
            return error_response("invalid status", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        comments = BlogComment.objects.filter(article__workspace_key=context.workspace_key).select_related("article")
        if review_state == "pending":
            comments = comments.filter(is_reviewed=False, is_approved=False)
        else:
            comments = comments.filter(is_approved=True)
        comments = comments.order_by("-created_at")[:100]
        return Response(
            [
                {
                    "id": comment.id,
                    "article_title": comment.article.title,
                    "article_slug": comment.article.slug,
                    "author_name": comment.author_name,
                    "content": comment.content,
                    "quote": comment.quote,
                    "created_at": comment.created_at.isoformat(),
                }
                for comment in comments
            ]
        )


class BlogCommentModerateView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, comment_id: int):
        context, denied = _moderation_context(request)
        if denied:
            return denied
        decision = str(request.data.get("decision", "")).strip()
        if decision not in {"approve", "reject"}:
            return error_response("invalid decision", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        approved = decision == "approve"
        with transaction.atomic():
            comment = get_object_or_404(
                BlogComment.objects.select_for_update().select_related("article"),
                pk=comment_id,
                article__workspace_key=context.workspace_key,
            )
            changed = not comment.is_reviewed or comment.is_approved != approved
            if changed:
                comment.is_reviewed = True
                comment.is_approved = approved
                comment.reviewed_by = context.actor[:120]
                comment.reviewed_at = timezone.now()
                comment.save(update_fields=["is_reviewed", "is_approved", "reviewed_by", "reviewed_at"])
                if not approved:
                    BlogCommentReport.objects.filter(comment=comment, status=BlogCommentReport.Status.OPEN).update(
                        status=BlogCommentReport.Status.HIDDEN,
                        reviewed_by=context.actor[:120],
                        reviewed_at=comment.reviewed_at,
                    )
                SecurityAuditEvent.objects.create(
                    event_type=SecurityAuditEvent.EventType.COMMENT_MODERATED,
                    actor=context.actor[:120],
                    role=context.role,
                    workspace_key=context.workspace_key,
                    path=request.path[:240],
                    detail=decision,
                    metadata={"comment_id": comment.pk, "article_id": comment.article_id},
                )
        return Response(
            {"id": comment.pk, "moderation_status": "approved" if approved else "rejected", "changed": changed}
        )


class BlogCommentReportCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, comment_id: int):
        context = context_from_request(request)
        if not context.authenticated or not request.META.get("HTTP_AUTHORIZATION", "").lower().startswith("bearer "):
            return error_response("请先登录后举报", ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN)
        user = jwt_user_from_request(request)
        if user is None:
            return error_response("请先登录后举报", ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN)
        restriction = active_restriction_for(user, context.workspace_key)
        if restriction:
            return error_response(
                f"评论与举报功能已暂停至 {timezone.localtime(restriction.expires_at):%Y-%m-%d %H:%M}，可在博客页申诉。",
                ErrorCode.FORBIDDEN,
                status.HTTP_403_FORBIDDEN,
            )
        comment = get_object_or_404(
            BlogComment.objects.select_related("article"),
            pk=comment_id,
            article__workspace_key=context.workspace_key,
            article__status=BlogArticle.Status.PUBLISHED,
            is_approved=True,
        )
        reason = str(request.data.get("reason", "")).strip()
        detail = str(request.data.get("detail", "")).strip()
        if reason not in BlogCommentReport.Reason.values or len(detail) > 500:
            return error_response("invalid report", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        existing = BlogCommentReport.objects.filter(comment=comment, reporter_name=context.actor).first()
        if existing:
            return Response({"id": existing.pk, "status": existing.status, "created": False})

        identity = sha256(f"{context.workspace_key}\0{context.actor}".encode()).hexdigest()
        rate_key = f"blog-report-hour:{identity}"
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
                "举报暂不可用，请稍后再试", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE
            )
        if recent_count > 10:
            return error_response("举报太频繁，请稍后再试", ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS)

        report, created = BlogCommentReport.objects.get_or_create(
            comment=comment,
            reporter_name=context.actor,
            defaults={"reason": reason, "detail": detail},
        )
        return Response(
            {"id": report.pk, "status": report.status, "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class BlogCommentReportListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        context, denied = _moderation_context(request)
        if denied:
            return denied
        reports = (
            BlogCommentReport.objects.filter(
                comment__article__workspace_key=context.workspace_key, status=BlogCommentReport.Status.OPEN
            )
            .select_related("comment__article")
            .order_by("-created_at")[:100]
        )
        return Response(
            [
                {
                    "id": report.pk,
                    "comment_id": report.comment_id,
                    "article_title": report.comment.article.title,
                    "comment_content": report.comment.content,
                    "reporter_name": report.reporter_name,
                    "reason": report.reason,
                    "detail": report.detail,
                    "created_at": report.created_at.isoformat(),
                }
                for report in reports
            ]
        )


class BlogCommentReportReviewView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, report_id: int):
        context, denied = _moderation_context(request)
        if denied:
            return denied
        decision = str(request.data.get("decision", "")).strip()
        if decision not in {"hide", "dismiss"}:
            return error_response("invalid decision", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        target_status = BlogCommentReport.Status.HIDDEN if decision == "hide" else BlogCommentReport.Status.DISMISSED
        report_ref = get_object_or_404(
            BlogCommentReport.objects.filter(comment__article__workspace_key=context.workspace_key).values(
                "comment_id"
            ),
            pk=report_id,
        )
        with transaction.atomic():
            comment = get_object_or_404(
                BlogComment.objects.select_for_update(),
                pk=report_ref["comment_id"],
                article__workspace_key=context.workspace_key,
            )
            report = get_object_or_404(
                BlogCommentReport.objects.select_for_update().select_related("comment__article"),
                pk=report_id,
                comment_id=comment.pk,
                comment__article__workspace_key=context.workspace_key,
            )
            if report.status != BlogCommentReport.Status.OPEN:
                if report.status == target_status:
                    return Response({"id": report.pk, "status": report.status, "changed": False})
                return error_response("report already reviewed", ErrorCode.VALIDATION_ERROR, status.HTTP_409_CONFLICT)
            reviewed_at = timezone.now()
            if decision == "hide":
                comment.is_approved = False
                comment.is_reviewed = True
                comment.reviewed_by = context.actor[:120]
                comment.reviewed_at = reviewed_at
                comment.save(update_fields=["is_approved", "is_reviewed", "reviewed_by", "reviewed_at"])
                BlogCommentReport.objects.filter(comment=comment, status=BlogCommentReport.Status.OPEN).update(
                    status=BlogCommentReport.Status.HIDDEN,
                    reviewed_by=context.actor[:120],
                    reviewed_at=reviewed_at,
                )
            else:
                report.status = target_status
                report.reviewed_by = context.actor[:120]
                report.reviewed_at = reviewed_at
                report.save(update_fields=["status", "reviewed_by", "reviewed_at"])
            SecurityAuditEvent.objects.create(
                event_type=SecurityAuditEvent.EventType.COMMENT_REPORT_REVIEWED,
                actor=context.actor[:120],
                role=context.role,
                workspace_key=context.workspace_key,
                path=request.path[:240],
                detail=decision,
                metadata={"report_id": report.pk, "comment_id": report.comment_id},
            )
        return Response({"id": report.pk, "status": target_status, "changed": True})
