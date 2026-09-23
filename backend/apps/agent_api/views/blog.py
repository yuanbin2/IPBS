import math

from .common import *


class BlogArticleListCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        articles = BlogArticle.objects.select_related("category", "knowledge_document").prefetch_related("tags").filter(
            workspace_key=get_workspace_key(request)
        )
        status_filter = request.query_params.get("status", BlogArticle.Status.PUBLISHED)
        if status_filter != "all":
            articles = articles.filter(status=status_filter)

        category = request.query_params.get("category")
        tag = request.query_params.get("tag")
        query = str(request.query_params.get("q", "")).strip()

        # 权限检查
        context = context_from_request(request)
        is_admin = context.authenticated and context.role in {UserProfile.Role.ADMIN, UserProfile.Role.OPERATOR}

        # 对于草稿和拒绝状态的文章，必须登录且只能看到自己的
        if status_filter in {BlogArticle.Status.DRAFT, BlogArticle.Status.REJECTED}:
            if not context.authenticated:
                return Response({"detail": "请先登录"}, status=status.HTTP_401_UNAUTHORIZED)
            if not is_admin:
                # 普通用户只能看到自己提交的（忽略大小写）
                articles = articles.filter(author_name__iexact=context.actor)
        else:
            # 已发布文章，支持按 author_name 过滤（忽略大小写）
            author_name = str(request.query_params.get("author_name", "")).strip()
            if author_name:
                articles = articles.filter(author_name__iexact=author_name)
            # 已登录非管理员用户查看已发布文章时，如果没指定 author_name，自动过滤为自己的
            elif context.authenticated and not is_admin:
                my_only = str(request.query_params.get("my", "")).strip()
                if my_only == "1":
                    articles = articles.filter(author_name__iexact=context.actor)

        if category:
            articles = articles.filter(category__slug=category)
        if tag:
            articles = articles.filter(tags__slug=tag)
        if query:
            articles = articles.filter(Q(title__icontains=query) | Q(summary__icontains=query) | Q(content__icontains=query))

        return Response([serialize_article(article) for article in articles.distinct()[:50]])

    def post(self, request):
        title = str(request.data.get("title", "")).strip()
        content = str(request.data.get("content", "")).strip()
        if not title or not content:
            return Response({"detail": "title and content are required"}, status=status.HTTP_400_BAD_REQUEST)

        context = context_from_request(request)

        # 已登录用户使用用户名，未登录用户使用提交的 author_name
        if context.authenticated:
            author_name = context.actor
        else:
            author_name = str(request.data.get("author_name", "")).strip()
            if not author_name:
                return Response({"detail": "请先登录或填写昵称"}, status=status.HTTP_400_BAD_REQUEST)

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
            payload={"article_slug": article.slug, "article_id": article.id, "title": article.title, "author_name": author_name},
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
            return Response({"detail": "image is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not upload.content_type.startswith("image/"):
            return Response({"detail": "only image files are supported"}, status=status.HTTP_400_BAD_REQUEST)

        suffix = Path(upload.name).suffix.lower() or ".png"
        if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}:
            return Response({"detail": "unsupported image format"}, status=status.HTTP_400_BAD_REQUEST)

        max_size = 5 * 1024 * 1024
        if upload.size > max_size:
            return Response({"detail": "image must be smaller than 5MB"}, status=status.HTTP_400_BAD_REQUEST)

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
            return Response(
                {"detail": "请先登录"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # 普通用户只能编辑自己的文章（忽略大小写）
        if not is_admin and article.author_name.lower() != context.actor.lower():
            return Response(
                {"detail": "只能编辑自己提交的文章"},
                status=status.HTTP_403_FORBIDDEN,
            )

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
            requester=str(request.data.get("requester", "blog-editor")).strip() if hasattr(request, "data") else "blog-editor",
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
            requester=str(request.data.get("requester", "blog-editor")).strip() if hasattr(request, "data") else "blog-editor",
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


class BlogAgentChatView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        message = str(request.data.get("message", "")).strip()
        if not message:
            return Response({"detail": "message is required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(message) > 800:
            return Response({"detail": "message must be shorter than 800 characters"}, status=status.HTTP_400_BAD_REQUEST)

        session = self._get_or_create_session(request)
        if session.is_blocked:
            return Response({"detail": "this visitor session is blocked"}, status=status.HTTP_403_FORBIDDEN)
        if self._is_rate_limited(session):
            return Response(
                {"detail": "提问太频繁了，请稍后再试。"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        BlogAgentMessage.objects.create(
            session=session,
            role=BlogAgentMessage.Role.USER,
            content=message,
        )

        agent = PublicBlogAgent(Path(settings.BASE_DIR).parent)
        answer = agent.answer(message)
        payload = answer.to_dict()

        if answer.blocked:
            BlogAgentSecurityEvent.objects.create(
                session=session,
                question=message,
                reason=answer.block_reason,
                ip_hash=session.ip_hash,
            )

        agent_message = BlogAgentMessage.objects.create(
            session=session,
            role=BlogAgentMessage.Role.AGENT,
            content=answer.answer,
            sources=payload["sources"],
            trace=answer.trace,
            token_usage=answer.token_usage,
        )
        session.save(update_fields=["updated_at"])

        return Response(
            {
                **payload,
                "session_key": session.session_key,
                "message": serialize_blog_agent_message(agent_message),
            }
        )

    def get(self, request):
        session_key = str(request.query_params.get("session_key", "")).strip()
        if not session_key:
            return Response({"messages": []})

        session = get_object_or_404(BlogAgentSession, session_key=session_key)
        messages = session.messages.all().order_by("-id")[:20]
        return Response(
            {
                "session_key": session.session_key,
                "messages": [serialize_blog_agent_message(message) for message in reversed(messages)],
            }
        )

    def _get_or_create_session(self, request) -> BlogAgentSession:
        session_key = str(request.data.get("session_key", "")).strip()
        if not session_key:
            session_key = uuid4().hex

        session, _ = BlogAgentSession.objects.get_or_create(
            session_key=session_key,
            defaults={
                "visitor_label": "匿名访客",
                "ip_hash": request_ip_hash(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:1000],
            },
        )
        return session

    def _is_rate_limited(self, session: BlogAgentSession) -> bool:
        since = timezone.now() - timedelta(seconds=BLOG_AGENT_RATE_WINDOW_SECONDS)
        recent_count = session.messages.filter(
            role=BlogAgentMessage.Role.USER,
            created_at__gte=since,
        ).count()
        return recent_count >= BLOG_AGENT_RATE_LIMIT


class BlogCommentCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, slug: str):
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))
        comments = article.comments.filter(is_approved=True)
        return Response(
            [
                {
                    "id": comment.id,
                    "author_name": comment.author_name,
                    "content": comment.content,
                    "created_at": comment.created_at.isoformat(),
                }
                for comment in comments
            ]
        )

    def post(self, request, slug: str):
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))
        author_name = str(request.data.get("author_name", "")).strip()
        content = str(request.data.get("content", "")).strip()
        if not author_name or not content:
            return Response({"detail": "author_name and content are required"}, status=status.HTTP_400_BAD_REQUEST)
        comment = BlogComment.objects.create(article=article, author_name=author_name, content=content)
        return Response(
            {
                "id": comment.id,
                "author_name": comment.author_name,
                "content": comment.content,
                "created_at": comment.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )
