import hashlib
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.simple_agent import SimpleToolCallingAgent

from .blog import (
    get_or_create_category,
    publish_article_to_knowledge_base,
    serialize_article,
    serialize_category,
    serialize_tag,
    set_article_tags,
    unique_slug,
)
from .blog_agent import PublicBlogAgent
from .models import (
    AgentRun,
    ArticleCategory,
    ArticleTag,
    BlogAgentMessage,
    BlogAgentSecurityEvent,
    BlogAgentSession,
    BlogArticle,
    BlogComment,
    Conversation,
    Document,
    KnowledgeBase,
    Message,
)
from .rag import get_default_knowledge_base, ingest_document, search_knowledge_base


def serialize_message(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "tool_calls": message.tool_calls,
        "sources": message.sources,
        "trace": message.trace,
        "token_usage": message.token_usage,
        "created_at": message.created_at.isoformat(),
    }


def serialize_knowledge_base(knowledge_base: KnowledgeBase) -> dict:
    return {
        "id": knowledge_base.id,
        "name": knowledge_base.name,
        "description": knowledge_base.description,
        "document_count": knowledge_base.documents.count(),
        "chunk_count": knowledge_base.chunks.count(),
        "created_at": knowledge_base.created_at.isoformat(),
        "updated_at": knowledge_base.updated_at.isoformat(),
    }


def serialize_document(document: Document) -> dict:
    return {
        "id": document.id,
        "knowledge_base_id": document.knowledge_base_id,
        "title": document.title,
        "content_type": document.content_type,
        "status": document.status,
        "error_message": document.error_message,
        "chunk_count": document.chunk_count,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


DEFAULT_MESSAGE_LIMIT = 30
MAX_MESSAGE_LIMIT = 50
BLOG_AGENT_RATE_LIMIT = 12
BLOG_AGENT_RATE_WINDOW_SECONDS = 60


def get_message_limit(request) -> int:
    try:
        limit = int(request.query_params.get("limit", DEFAULT_MESSAGE_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_MESSAGE_LIMIT
    return max(1, min(limit, MAX_MESSAGE_LIMIT))


def request_ip_hash(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded_for.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    if not ip:
        return ""
    return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode("utf-8")).hexdigest()


def serialize_blog_agent_message(message: BlogAgentMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "sources": message.sources,
        "trace": message.trace,
        "token_usage": message.token_usage,
        "created_at": message.created_at.isoformat(),
    }


def serialize_conversation(
    conversation: Conversation,
    include_messages: bool = False,
    messages: list[Message] | None = None,
    has_more_before: bool = False,
    has_more_after: bool = False,
    matched_message_id: int | None = None,
) -> dict:
    data = {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }
    if matched_message_id:
        data["matched_message_id"] = matched_message_id
    if include_messages:
        selected_messages = messages if messages is not None else list(conversation.messages.all())
        data["messages"] = [serialize_message(message) for message in selected_messages]
        data["has_more_before"] = has_more_before
        data["has_more_after"] = has_more_after
    return data


class ConversationListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        query = str(request.query_params.get("q", "")).strip()
        conversations = Conversation.objects.all()
        if query:
            conversations = conversations.filter(
                Q(title__icontains=query) | Q(messages__content__icontains=query)
            ).distinct()

        results = []
        for conversation in conversations[:30]:
            matched_message_id = None
            if query:
                match = conversation.messages.filter(content__icontains=query).first()
                matched_message_id = match.id if match else None
            results.append(
                serialize_conversation(
                    conversation,
                    matched_message_id=matched_message_id,
                )
            )
        return Response(results)


class ConversationDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk: int):
        conversation = get_object_or_404(Conversation, pk=pk)
        limit = get_message_limit(request)
        before = request.query_params.get("before")
        anchor = request.query_params.get("anchor")

        messages_queryset = conversation.messages.all()
        has_more_after = False

        if anchor:
            anchor_message = get_object_or_404(messages_queryset, pk=anchor)
            before_count = max(1, limit // 2)
            after_count = max(0, limit - before_count)
            before_messages = list(
                messages_queryset.filter(id__lte=anchor_message.id).order_by("-id")[:before_count]
            )
            after_messages = list(
                messages_queryset.filter(id__gt=anchor_message.id).order_by("id")[:after_count]
            )
            messages = [*reversed(before_messages), *after_messages]
            has_more_after = messages_queryset.filter(id__gt=messages[-1].id).exists() if messages else False
        elif before:
            messages = list(messages_queryset.filter(id__lt=before).order_by("-id")[:limit])
            messages = list(reversed(messages))
        else:
            messages = list(messages_queryset.order_by("-id")[:limit])
            messages = list(reversed(messages))

        has_more_before = messages_queryset.filter(id__lt=messages[0].id).exists() if messages else False
        return Response(
            serialize_conversation(
                conversation,
                include_messages=True,
                messages=messages,
                has_more_before=has_more_before,
                has_more_after=has_more_after,
            )
        )


class AgentChatView(APIView):
    authentication_classes = []
    permission_classes = []

    @transaction.atomic
    def post(self, request):
        message = str(request.data.get("message", "")).strip()
        if not message:
            return Response(
                {"detail": "message is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        conversation = self._get_or_create_conversation(request.data.get("conversation_id"), message)
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content=message,
        )

        project_root = Path(settings.BASE_DIR).parent
        agent = SimpleToolCallingAgent(project_root)
        response = agent.chat(message)
        response_data = response.to_dict()

        Message.objects.create(
            conversation=conversation,
            role=Message.Role.AGENT,
            content=response.answer,
            tool_calls=response_data["tool_calls"],
            sources=response_data["sources"],
            trace=response.trace,
            token_usage=response.token_usage,
        )
        AgentRun.objects.create(
            conversation=conversation,
            input_message=message,
            route=response.route,
            tool_calls=response_data["tool_calls"],
            sources=response_data["sources"],
            trace=response.trace,
            token_usage=response.token_usage,
        )

        conversation.save(update_fields=["updated_at"])
        return Response(
            {
                **response_data,
                "conversation": serialize_conversation(conversation),
            }
        )

    def _get_or_create_conversation(self, conversation_id, message: str) -> Conversation:
        if conversation_id:
            return get_object_or_404(Conversation, pk=conversation_id)

        title = message[:40]
        if len(message) > 40:
            title = f"{title}..."
        return Conversation.objects.create(title=title)


class KnowledgeBaseListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        get_default_knowledge_base()
        knowledge_bases = KnowledgeBase.objects.all()
        return Response([serialize_knowledge_base(item) for item in knowledge_bases])

    def post(self, request):
        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response({"detail": "name is required"}, status=status.HTTP_400_BAD_REQUEST)

        knowledge_base, created = KnowledgeBase.objects.get_or_create(
            name=name,
            defaults={"description": str(request.data.get("description", "")).strip()},
        )
        if not created:
            knowledge_base.description = str(request.data.get("description", knowledge_base.description)).strip()
            knowledge_base.save(update_fields=["description", "updated_at"])
        return Response(serialize_knowledge_base(knowledge_base), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class DocumentListUploadView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        knowledge_base_id = request.query_params.get("knowledge_base_id")
        documents = Document.objects.select_related("knowledge_base")
        if knowledge_base_id:
            documents = documents.filter(knowledge_base_id=knowledge_base_id)
        return Response([serialize_document(document) for document in documents[:50]])

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "file is required"}, status=status.HTTP_400_BAD_REQUEST)

        suffix = Path(upload.name).suffix.lower()
        if suffix not in {".md", ".markdown", ".txt", ".pdf"}:
            return Response(
                {"detail": "only Markdown, txt and PDF files are supported"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        knowledge_base_id = request.data.get("knowledge_base_id")
        if knowledge_base_id:
            knowledge_base = get_object_or_404(KnowledgeBase, pk=knowledge_base_id)
        else:
            knowledge_base = get_default_knowledge_base()

        title = str(request.data.get("title") or Path(upload.name).stem).strip()
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            title=title,
            source_file=upload,
            content_type=getattr(upload, "content_type", "") or suffix.lstrip("."),
        )
        document = ingest_document(document)
        return Response(serialize_document(document), status=status.HTTP_201_CREATED)


class DocumentReindexView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        document = get_object_or_404(Document, pk=pk)
        document = ingest_document(document)
        return Response(serialize_document(document))


class KnowledgeSearchView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        query = str(request.data.get("query", "")).strip()
        if not query:
            return Response({"detail": "query is required"}, status=status.HTTP_400_BAD_REQUEST)

        knowledge_base_id = request.data.get("knowledge_base_id")
        limit = request.data.get("limit", 5)
        try:
            limit = max(1, min(int(limit), 10))
        except (TypeError, ValueError):
            limit = 5

        results = search_knowledge_base(
            query,
            knowledge_base_id=int(knowledge_base_id) if knowledge_base_id else None,
            limit=limit,
        )
        return Response(
            [
                {
                    "document_id": item.document_id,
                    "document_title": item.document_title,
                    "chunk_id": item.chunk_id,
                    "chunk_index": item.chunk_index,
                    "content": item.content,
                    "score": item.score,
                }
                for item in results
            ]
        )


class BlogArticleListCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        articles = BlogArticle.objects.select_related("category", "knowledge_document").prefetch_related("tags")
        status_filter = request.query_params.get("status", BlogArticle.Status.PUBLISHED)
        if status_filter != "all":
            articles = articles.filter(status=status_filter)

        category = request.query_params.get("category")
        tag = request.query_params.get("tag")
        query = str(request.query_params.get("q", "")).strip()
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

        article = BlogArticle.objects.create(
            title=title,
            slug=unique_slug(BlogArticle, request.data.get("slug") or title, max_length=200),
            summary=str(request.data.get("summary", "")).strip(),
            content=content,
            category=get_or_create_category(request.data.get("category")),
            status=str(request.data.get("status", BlogArticle.Status.DRAFT)),
        )
        set_article_tags(article, request.data.get("tags", []))
        if article.status == BlogArticle.Status.PUBLISHED or request.data.get("publish"):
            article = publish_article_to_knowledge_base(article)
        return Response(serialize_article(article, include_content=True), status=status.HTTP_201_CREATED)


class BlogImageUploadView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
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

        filename = f"blog/{uuid4().hex}{suffix}"
        saved_path = default_storage.save(filename, ContentFile(upload.read()))
        media_url = f"/{settings.MEDIA_URL.lstrip('/')}{saved_path}"
        image_url = request.build_absolute_uri(media_url)
        return Response(
            {
                "url": image_url,
                "markdown": f"![{Path(upload.name).stem}]({image_url})",
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
        )
        article.view_count += 1
        article.save(update_fields=["view_count", "updated_at"])
        return Response(serialize_article(article, include_content=True))

    def patch(self, request, slug: str):
        article = get_object_or_404(BlogArticle, slug=slug)
        if "title" in request.data:
            article.title = str(request.data["title"]).strip()
        if "summary" in request.data:
            article.summary = str(request.data["summary"]).strip()
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
            article = publish_article_to_knowledge_base(article)
        return Response(serialize_article(article, include_content=True))


class BlogArticlePublishView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, slug: str):
        article = get_object_or_404(BlogArticle, slug=slug)
        article = publish_article_to_knowledge_base(article)
        return Response(serialize_article(article, include_content=True))


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
        articles = BlogArticle.objects.filter(status=BlogArticle.Status.PUBLISHED).order_by("-published_at")
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
        article = get_object_or_404(BlogArticle, slug=slug)
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
        article = get_object_or_404(BlogArticle, slug=slug)
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
