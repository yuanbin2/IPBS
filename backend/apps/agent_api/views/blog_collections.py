"""领域知识目录（B-042A 私有目录 / B-042B 审核与公开读取）。

权限模型：写操作一律要求真实 JWT，并以 owner FK + profile workspace 判定，
不信任请求体中的 owner/workspace/status。公开读取只暴露已批准快照，
并逐次用同 workspace 的 published 文章批量解析，失效文章立即隐藏。
"""

import math

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import get_or_create_profile, jwt_user_from_request, normalize_workspace_key

from ..exceptions import ErrorCode
from ..models import (
    ApprovalRequest,
    BlogCollection,
    BlogCollectionAutoRule,
    BlogCollectionEntry,
    BlogCollectionNode,
)
from ..services import blog_collections as collection_service
from ..services.collection_archive import (
    CONFLICT_SKIP,
    MAX_ARCHIVE_BYTES,
    ArchiveError,
    apply_import,
    build_archive_bytes,
    export_filename,
    plan_import,
    read_archive,
)
from ..services.blog_collections import (
    MAX_DESCRIPTION,
    MAX_SEARCH_QUERY,
    CollectionError,
    apply_auto_rules,
    build_snapshot,
    clean_text,
    collection_reading_sequence,
    collection_slug,
    ensure_depth_ok,
    ensure_move_target,
    ensure_node_capacity,
    ensure_parent_in_collection,
    get_entry_article,
    published_visible_articles,
    reorder_ids_match,
    resolve_auto_rule_targets,
    serialize_auto_rule,
    serialize_collection_summary,
    serialize_draft_tree,
    serialize_public_article,
    snapshot_sha256,
)
from .common import error_response, get_workspace_key

WRITE_HOURLY_LIMIT = 300
SUBMIT_HOURLY_LIMIT = 10
PUBLIC_PAGE_SIZE = 24
MAX_BATCH_ENTRIES = 50
MAX_AUTO_RULES = 20


def collection_principal(request):
    user = jwt_user_from_request(request)
    if user is None:
        return None
    profile = get_or_create_profile(user)
    return user, normalize_workspace_key(profile.workspace_key)


def _check_write_rate(user) -> Response | None:
    try:
        key = f"blog-collection-write-hour:{user.pk}"
        count = 1 if cache.add(key, 1, timeout=3600) else cache.incr(key)
        if count > WRITE_HOURLY_LIMIT:
            return error_response(
                "目录操作过于频繁，请稍后再试", ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS
            )
    except (RedisError, ConnectionError, OSError):
        return error_response("目录服务暂不可用", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE)
    return None


def _get_owned_collection(public_id, principal) -> BlogCollection | None:
    user, workspace_key = principal
    try:
        key = str(public_id).strip()
    except (TypeError, ValueError):
        return None
    return (
        BlogCollection.objects.filter(public_id=key, owner=user, workspace_key=workspace_key)
        .exclude(archived_at__isnull=False)
        .first()
    )


def _expected_version(collection: BlogCollection, data) -> int | None:
    """Return the valid expected_version, or None on mismatch/absence."""
    raw = data.get("expected_version") if isinstance(data, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if raw == collection.draft_version else None


class BlogCollectionMineView(APIView):
    """GET /blog/collections/mine/ —— 本人目录及发布状态。"""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        user, workspace_key = principal
        collections = BlogCollection.objects.filter(owner=user, workspace_key=workspace_key)
        items = []
        for collection in collections:
            summary = serialize_collection_summary(collection)
            approval = collection.pending_approval
            if approval is not None:
                summary["pending"] = {
                    "id": approval.pk,
                    "status": approval.status,
                    "review_note": approval.review_note,
                }
            last_decision = (
                ApprovalRequest.objects.filter(blog_collections=collection)
                .exclude(status=ApprovalRequest.Status.PENDING)
                .order_by("-reviewed_at", "-id")
                .first()
            )
            if last_decision is not None:
                summary["last_review"] = {
                    "id": last_decision.pk,
                    "status": last_decision.status,
                    "review_note": last_decision.review_note,
                    "result": last_decision.result,
                }
            items.append(summary)
        return Response({"items": items})


class BlogCollectionDraftView(APIView):
    """GET/PATCH/DELETE /blog/collections/<uuid>/draft/ —— 私有工作版。"""

    authentication_classes = []
    permission_classes = []

    @transaction.atomic
    def get(self, request, public_id):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        collection = (
            BlogCollection.objects.select_for_update()
            .filter(public_id=str(public_id), owner=principal[0], workspace_key=principal[1])
            .exclude(archived_at__isnull=False)
            .first()
        )
        if collection is None:
            return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        # 打开工作版时幂等补齐：启用中的规则会把新发布的匹配文章自动收录。
        applied = apply_auto_rules(collection)
        payload = serialize_draft_tree(collection)
        payload["auto_applied"] = applied["added"]
        return Response(payload)

    @transaction.atomic
    def patch(self, request, public_id):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        denied = _check_write_rate(principal[0])
        if denied:
            return denied
        collection = (
            BlogCollection.objects.select_for_update()
            .filter(public_id=str(public_id), owner=principal[0], workspace_key=principal[1])
            .exclude(archived_at__isnull=False)
            .first()
        )
        if collection is None:
            return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        if _expected_version(collection, request.data if isinstance(request.data, dict) else {}) is None:
            return error_response(
                "目录已被其他标签页修改，请刷新后重试",
                ErrorCode.CONFLICT,
                status.HTTP_409_CONFLICT,
            )
        if not isinstance(request.data, dict):
            return error_response("请求体必须是 JSON 对象", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        fields = []
        try:
            if "title" in request.data:
                collection.title = clean_text(
                    request.data.get("title"), field="领域标题", max_length=120, required=True
                )
                fields.append("title")
            if "description" in request.data:
                collection.description = clean_text(
                    request.data.get("description"), field="领域简介", max_length=MAX_DESCRIPTION
                )
                fields.append("description")
        except CollectionError as exc:
            return error_response(str(exc), ErrorCode.VALIDATION_ERROR, exc.http_status)
        if fields:
            collection.draft_version += 1
            collection.save(update_fields=[*fields, "draft_version", "updated_at"])
        return Response(serialize_draft_tree(collection))

    @transaction.atomic
    def delete(self, request, public_id):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        collection = (
            BlogCollection.objects.select_for_update()
            .filter(public_id=str(public_id), owner=principal[0], workspace_key=principal[1])
            .first()
        )
        if collection is None:
            return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        if collection.published_snapshot:
            # 公开过的领域只能归档：保留历史快照与外链数据，不再出现在公开列表。
            collection.archived_at = timezone.now()
            collection.pending_snapshot = None
            collection.pending_approval = None
            collection.save(update_fields=["archived_at", "pending_snapshot", "pending_approval", "updated_at"])
            ApprovalRequest.objects.filter(
                pk__in=ApprovalRequest.objects.filter(
                    blog_collections=collection, status=ApprovalRequest.Status.PENDING
                ).values_list("pk", flat=True)
            ).update(status=ApprovalRequest.Status.REJECTED, result="领域已归档，待审自动关闭。")
            return Response({"archived": True, "detail": "已公开领域已归档，公开列表不再展示。"})
        collection.delete()
        return Response({"archived": False, "detail": "私有草稿已删除。"})


class BlogCollectionNodeCreateView(APIView):
    """POST /blog/collections/<uuid>/nodes/ —— 新增课程/章节/知识点节点。"""

    authentication_classes = []
    permission_classes = []

    def post(self, request, public_id):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        user, _ = principal
        denied = _check_write_rate(user)
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return error_response("请求体必须是 JSON 对象", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                collection = (
                    BlogCollection.objects.select_for_update()
                    .filter(public_id=str(public_id), owner=user, workspace_key=principal[1])
                    .exclude(archived_at__isnull=False)
                    .first()
                )
                if collection is None:
                    return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
                if _expected_version(collection, request.data) is None:
                    return error_response(
                        "目录已被其他标签页修改，请刷新后重试", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT
                    )
                ensure_node_capacity(collection)
                parent = ensure_parent_in_collection(collection, request.data.get("parent_id"))
                title = clean_text(request.data.get("title"), field="节点标题", max_length=120, required=True)
                description = clean_text(request.data.get("description"), field="节点说明", max_length=MAX_DESCRIPTION)
                node = BlogCollectionNode(collection=collection, parent=parent, title=title, description=description)
                if parent is not None:
                    ensure_move_target(collection, node, parent)
                    ensure_depth_ok(collection, node, parent)
                    node.position = parent.children.count()
                else:
                    ensure_depth_ok(collection, node, None)
                    node.position = collection.nodes.filter(parent__isnull=True).count()
                node.save()
                collection.draft_version += 1
                collection.save(update_fields=["draft_version", "updated_at"])
        except CollectionError as exc:
            code = ErrorCode.CONFLICT if "环" in str(exc) else ErrorCode.VALIDATION_ERROR
            return error_response(str(exc), code, exc.http_status)
        return Response(
            {
                "node": {
                    "id": node.id,
                    "parent": node.parent_id,
                    "title": node.title,
                    "description": node.description,
                    "position": node.position,
                },
                "draft_version": collection.draft_version,
            },
            status=status.HTTP_201_CREATED,
        )


class BlogCollectionNodeDetailView(APIView):
    """PATCH/DELETE /blog/collections/<uuid>/nodes/<int:node_id>/ —— 改名/移动/删除。"""

    authentication_classes = []
    permission_classes = []

    def _load(self, request, public_id, node_id):
        principal = collection_principal(request)
        if principal is None:
            return (
                None,
                None,
                None,
                error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED),
            )
        collection = (
            BlogCollection.objects.select_for_update()
            .filter(public_id=str(public_id), owner=principal[0], workspace_key=principal[1])
            .exclude(archived_at__isnull=False)
            .first()
        )
        if collection is None:
            return None, None, None, error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        node = collection.nodes.filter(pk=node_id).first()
        if node is None:
            return None, None, None, error_response("节点不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        return principal, collection, node, None

    @transaction.atomic
    def patch(self, request, public_id, node_id: int):
        principal, collection, node, failure = self._load(request, public_id, node_id)
        if failure:
            return failure
        if not isinstance(request.data, dict) or _expected_version(collection, request.data) is None:
            return error_response("目录已被其他标签页修改，请刷新后重试", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT)
        try:
            if "title" in request.data:
                node.title = clean_text(request.data.get("title"), field="节点标题", max_length=120, required=True)
            if "description" in request.data:
                node.description = clean_text(
                    request.data.get("description"), field="节点说明", max_length=MAX_DESCRIPTION
                )
            if "parent_id" in request.data:
                parent = ensure_parent_in_collection(collection, request.data.get("parent_id"))
                if parent is not None:
                    ensure_move_target(collection, node, parent)
                    ensure_depth_ok(collection, node, parent)
                node.parent = parent
            node.save()
            collection.draft_version += 1
            collection.save(update_fields=["draft_version", "updated_at"])
        except CollectionError as exc:
            code = ErrorCode.CONFLICT if "移动" in str(exc) or "环" in str(exc) else ErrorCode.VALIDATION_ERROR
            return error_response(str(exc), code, exc.http_status)
        return Response(
            {
                "node": {
                    "id": node.id,
                    "parent": node.parent_id,
                    "title": node.title,
                    "description": node.description,
                    "position": node.position,
                },
                "draft_version": collection.draft_version,
            }
        )

    @transaction.atomic
    def delete(self, request, public_id, node_id: int):
        principal, collection, node, failure = self._load(request, public_id, node_id)
        if failure:
            return failure
        if not isinstance(request.data, dict) or _expected_version(collection, request.data) is None:
            return error_response("目录已被其他标签页修改，请刷新后重试", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT)
        descendant_ids = [node.pk]
        frontier = [node.pk]
        while frontier:
            children = list(
                BlogCollectionNode.objects.filter(collection=collection, parent_id__in=frontier).values_list(
                    "pk", flat=True
                )
            )
            children = [pk for pk in children if pk not in descendant_ids]
            descendant_ids.extend(children)
            frontier = children
        BlogCollectionEntry.objects.filter(collection=collection, node_id__in=descendant_ids).delete()
        BlogCollectionNode.objects.filter(collection=collection, pk__in=descendant_ids).delete()
        collection.draft_version += 1
        collection.save(update_fields=["draft_version", "updated_at"])
        return Response({"deleted": True, "draft_version": collection.draft_version})


class BlogCollectionEntryView(APIView):
    """POST /blog/collections/<uuid>/entries/ —— 收录已发布文章（支持批量）。

    请求体：{node_id, article_id} 或 {node_id, article_ids: [...]}，兼容单篇写法。
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request, public_id):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        user, _ = principal
        denied = _check_write_rate(user)
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return error_response("请求体必须是 JSON 对象", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                collection = (
                    BlogCollection.objects.select_for_update()
                    .filter(public_id=str(public_id), owner=user, workspace_key=principal[1])
                    .exclude(archived_at__isnull=False)
                    .first()
                )
                if collection is None:
                    return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
                if _expected_version(collection, request.data) is None:
                    return error_response(
                        "目录已被其他标签页修改，请刷新后重试", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT
                    )
                node = ensure_parent_in_collection(collection, request.data.get("node_id"))
                raw_ids = request.data.get("article_ids")
                if raw_ids is None:
                    raw_ids = [request.data.get("article_id")]
                if not isinstance(raw_ids, list) or not raw_ids:
                    return error_response(
                        "请选择至少一篇已发布文章", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
                    )
                if len(raw_ids) > MAX_BATCH_ENTRIES:
                    return error_response(
                        f"一次最多加入 {MAX_BATCH_ENTRIES} 篇文章",
                        ErrorCode.VALIDATION_ERROR,
                        status.HTTP_400_BAD_REQUEST,
                    )
                known_ids = set(collection.entries.values_list("article_id", flat=True))
                position = collection.entries.filter(node=node).count()
                created = []
                skipped: list[int] = []
                for raw in raw_ids:
                    article = get_entry_article(collection, raw)
                    if article.pk in known_ids:
                        skipped.append(article.pk)
                        continue
                    # 走服务层常量（而非本模块的副本），保证容量上限可被统一调整/测试。
                    if len(known_ids) >= collection_service.MAX_ENTRIES:
                        return error_response(
                            f"单个领域最多收录 {collection_service.MAX_ENTRIES} 篇文章",
                            ErrorCode.VALIDATION_ERROR,
                            status.HTTP_400_BAD_REQUEST,
                        )
                    entry = BlogCollectionEntry.objects.create(
                        collection=collection, node=node, article=article, position=position
                    )
                    known_ids.add(article.pk)
                    position += 1
                    created.append(entry)
                if created:
                    collection.draft_version += 1
                    collection.save(update_fields=["draft_version", "updated_at"])
                elif skipped:
                    # 整批都已收录：沿用单篇加入时的 409 语义，前端据此提示“已经在了”。
                    return error_response(
                        "这些文章已在该领域中", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT
                    )
        except CollectionError as exc:
            return error_response(str(exc), ErrorCode.VALIDATION_ERROR, exc.http_status)
        return Response(
            {
                "entries": [
                    {
                        "id": entry.id,
                        "node": entry.node_id,
                        "position": entry.position,
                        "article_id": entry.article_id,
                    }
                    for entry in created
                ],
                "entry": {
                    "id": created[0].id,
                    "node": created[0].node_id,
                    "position": created[0].position,
                    "article_id": created[0].article_id,
                }
                if created
                else None,
                "added": len(created),
                "skipped": skipped,
                "draft_version": collection.draft_version,
            },
            status=status.HTTP_201_CREATED,
        )


class BlogCollectionEntryDetailView(APIView):
    """DELETE /blog/collections/<uuid>/entries/<int:entry_id>/ —— 移除文章。"""

    authentication_classes = []
    permission_classes = []

    @transaction.atomic
    def delete(self, request, public_id, entry_id: int):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        collection = (
            BlogCollection.objects.select_for_update()
            .filter(public_id=str(public_id), owner=principal[0], workspace_key=principal[1])
            .exclude(archived_at__isnull=False)
            .first()
        )
        if collection is None:
            return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        if not isinstance(request.data, dict) or _expected_version(collection, request.data) is None:
            return error_response("目录已被其他标签页修改，请刷新后重试", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT)
        entry = collection.entries.filter(pk=entry_id).first()
        if entry is None:
            return error_response("文章引用不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        entry.delete()
        collection.draft_version += 1
        collection.save(update_fields=["draft_version", "updated_at"])
        return Response({"deleted": True, "draft_version": collection.draft_version})


class BlogCollectionAutoRuleView(APIView):
    """GET/POST /blog/collections/<uuid>/auto-rules/ —— 自动收录规则。

    规则命中「已发布 + 指定分类（+可选标签）」的文章，把它们自动挂到目标节点下。
    规则本身不进入公开快照，只影响私有工作版的补齐。
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request, public_id):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        collection = _get_owned_collection(public_id, principal)
        if collection is None:
            return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        rules = collection.auto_rules.select_related("node", "category", "tag").all()
        return Response({"items": [serialize_auto_rule(rule) for rule in rules]})

    @transaction.atomic
    def post(self, request, public_id):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        denied = _check_write_rate(principal[0])
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return error_response("请求体必须是 JSON 对象", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        collection = (
            BlogCollection.objects.select_for_update()
            .filter(public_id=str(public_id), owner=principal[0], workspace_key=principal[1])
            .exclude(archived_at__isnull=False)
            .first()
        )
        if collection is None:
            return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        try:
            node, category, tag = resolve_auto_rule_targets(
                collection,
                request.data.get("node_id"),
                category_id=request.data.get("category_id"),
                category_slug=request.data.get("category_slug"),
                tag_id=request.data.get("tag_id"),
            )
        except CollectionError as exc:
            return error_response(str(exc), ErrorCode.VALIDATION_ERROR, exc.http_status)
        if collection.auto_rules.filter(node=node, category=category, tag=tag).exists():
            return error_response("这条规则已经存在", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT)
        if collection.auto_rules.count() >= MAX_AUTO_RULES:
            return error_response(
                f"单个领域最多 {MAX_AUTO_RULES} 条自动收录规则",
                ErrorCode.VALIDATION_ERROR,
                status.HTTP_400_BAD_REQUEST,
            )
        rule = BlogCollectionAutoRule.objects.create(
            collection=collection,
            node=node,
            category=category,
            tag=tag,
            enabled=bool(request.data.get("enabled", True)),
        )
        applied = apply_auto_rules(collection) if rule.enabled else {"added": 0, "rules": 0}
        return Response(
            {"rule": serialize_auto_rule(rule), "added": applied["added"], "draft_version": collection.draft_version},
            status=status.HTTP_201_CREATED,
        )


class BlogCollectionAutoRuleDetailView(APIView):
    """PATCH/DELETE /blog/collections/<uuid>/auto-rules/<int:rule_id>/。"""

    authentication_classes = []
    permission_classes = []

    @transaction.atomic
    def patch(self, request, public_id, rule_id: int):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        denied = _check_write_rate(principal[0])
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return error_response("请求体必须是 JSON 对象", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        collection = (
            BlogCollection.objects.select_for_update()
            .filter(public_id=str(public_id), owner=principal[0], workspace_key=principal[1])
            .exclude(archived_at__isnull=False)
            .first()
        )
        if collection is None:
            return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        rule = collection.auto_rules.filter(pk=rule_id).first()
        if rule is None:
            return error_response("规则不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        if "enabled" in request.data:
            rule.enabled = bool(request.data.get("enabled"))
            rule.save(update_fields=["enabled"])
        applied = {"added": 0}
        if rule.enabled and request.data.get("apply"):
            applied = apply_auto_rules(collection)
        return Response(
            {"rule": serialize_auto_rule(rule), "added": applied["added"], "draft_version": collection.draft_version}
        )

    @transaction.atomic
    def delete(self, request, public_id, rule_id: int):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        collection = _get_owned_collection(public_id, principal)
        if collection is None:
            return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        rule = collection.auto_rules.filter(pk=rule_id).first()
        if rule is None:
            return error_response("规则不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        rule.delete()
        return Response({"deleted": True, "draft_version": collection.draft_version})


class BlogCollectionReorderView(APIView):
    """POST /blog/collections/<uuid>/reorder/ —— 单个父节点下完整顺序重排。"""

    authentication_classes = []
    permission_classes = []

    def post(self, request, public_id):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        user, _ = principal
        denied = _check_write_rate(user)
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return error_response("请求体必须是 JSON 对象", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        scope = request.data.get("scope")
        if scope not in {"nodes", "entries"}:
            return error_response(
                "scope 必须是 nodes 或 entries", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )
        try:
            with transaction.atomic():
                collection = (
                    BlogCollection.objects.select_for_update()
                    .filter(public_id=str(public_id), owner=user, workspace_key=principal[1])
                    .exclude(archived_at__isnull=False)
                    .first()
                )
                if collection is None:
                    return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
                if _expected_version(collection, request.data) is None:
                    return error_response(
                        "目录已被其他标签页修改，请刷新后重试", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT
                    )
                parent = ensure_parent_in_collection(collection, request.data.get("parent_id"))
                if scope == "nodes":
                    siblings = list(collection.nodes.filter(parent=parent).order_by("position", "id"))
                    ordered = reorder_ids_match([node.pk for node in siblings], request.data.get("ordered_ids"))
                    order_map = {pk: index for index, pk in enumerate(ordered)}
                    for node in siblings:
                        node.position = order_map[node.pk]
                        node.save(update_fields=["position", "updated_at"])
                else:
                    siblings = list(collection.entries.filter(node=parent).order_by("position", "id"))
                    ordered = reorder_ids_match([entry.pk for entry in siblings], request.data.get("ordered_ids"))
                    order_map = {pk: index for index, pk in enumerate(ordered)}
                    for entry in siblings:
                        entry.position = order_map[entry.pk]
                        entry.save(update_fields=["position"])
                collection.draft_version += 1
                collection.save(update_fields=["draft_version", "updated_at"])
        except CollectionError as exc:
            return error_response(str(exc), ErrorCode.VALIDATION_ERROR, exc.http_status)
        return Response({"draft_version": collection.draft_version})


class BlogCollectionSubmitView(APIView):
    """POST /blog/collections/<uuid>/submit/ —— 冻结待审快照并进入审批。"""

    authentication_classes = []
    permission_classes = []

    def post(self, request, public_id):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        user, _ = principal
        try:
            key = f"blog-collection-submit-hour:{user.pk}"
            count = 1 if cache.add(key, 1, timeout=3600) else cache.incr(key)
            if count > SUBMIT_HOURLY_LIMIT:
                return error_response(
                    "提交过于频繁，请稍后再试", ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS
                )
        except (RedisError, ConnectionError, OSError):
            return error_response(
                "目录服务暂不可用", ErrorCode.UPSTREAM_UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE
            )
        with transaction.atomic():
            collection = (
                BlogCollection.objects.select_for_update()
                .filter(public_id=str(public_id), owner=user, workspace_key=principal[1])
                .exclude(archived_at__isnull=False)
                .first()
            )
            if collection is None:
                return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
            if collection.pending_approval_id and collection.pending_snapshot:
                pending = collection.pending_approval
                if pending and pending.status == ApprovalRequest.Status.PENDING:
                    if collection.pending_snapshot.get("draft_version") == collection.draft_version:
                        return Response(
                            {
                                "approval_id": pending.pk,
                                "status": pending.status,
                                "detail": "当前版本已在待审中。",
                            }
                        )
                    pending.status = ApprovalRequest.Status.REJECTED
                    pending.result = "已被作者的新版本提交替代。"
                    pending.reviewed_at = timezone.now()
                    pending.save(update_fields=["status", "result", "reviewed_at"])
            # 冻结前先补齐规则命中的新文章，避免快照漏掉最新内容。
            apply_auto_rules(collection)
            snapshot = build_snapshot(collection)
            approval = ApprovalRequest.objects.create(
                action=ApprovalRequest.Action.PUBLISH_BLOG_COLLECTION,
                workspace_key=collection.workspace_key,
                title=f"发布领域目录：{collection.title}",
                description=f"目录包含 {len(snapshot['nodes'])} 个节点、{len(snapshot['entries'])} 篇文章引用；快照哈希见 payload。",
                payload={
                    "collection_id": collection.pk,
                    "collection_public_id": str(collection.public_id),
                    "submit_version": collection.draft_version,
                    "snapshot_hash": snapshot_sha256(snapshot),
                },
                requester=user.username,
            )
            collection.pending_snapshot = snapshot
            collection.pending_approval = approval
            collection.save(update_fields=["pending_snapshot", "pending_approval", "updated_at"])
        return Response(
            {
                "approval_id": approval.pk,
                "status": approval.status,
                "detail": "待审快照已冻结，等待管理员审核。",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class BlogCollectionPublicListView(APIView):
    """GET /blog/collections/ 公开领域列表；POST 创建私有领域草稿。"""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录后再创建领域目录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        user, workspace_key = principal
        denied = _check_write_rate(user)
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return error_response("请求体必须是 JSON 对象", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        try:
            title = clean_text(request.data.get("title"), field="领域标题", max_length=120, required=True)
            description = clean_text(request.data.get("description"), field="领域简介", max_length=MAX_DESCRIPTION)
        except CollectionError as exc:
            return error_response(str(exc), ErrorCode.VALIDATION_ERROR, exc.http_status)
        with transaction.atomic():
            base_slug = collection_slug(title)
            slug = base_slug
            suffix = 2
            while BlogCollection.objects.filter(workspace_key=workspace_key, owner=user, slug=slug).exists():
                slug = f"{base_slug[:130]}-{suffix}"
                suffix += 1
                if suffix > 50:
                    slug = f"collection-{timezone.now().timestamp():.0f}"
                    break
            collection = BlogCollection.objects.create(
                owner=user,
                workspace_key=workspace_key,
                title=title,
                slug=slug,
                description=description,
            )
        return Response(serialize_draft_tree(collection), status=status.HTTP_201_CREATED)

    def get(self, request):
        workspace_key = get_workspace_key(request)
        query = str(request.query_params.get("q", "")).strip()
        if len(query) > MAX_SEARCH_QUERY:
            return error_response("关键词过长", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 12))
        except (TypeError, ValueError):
            return error_response("页码无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        if page < 1 or page > 10000 or page_size < 1 or page_size > PUBLIC_PAGE_SIZE:
            return error_response("页码或每页数量超出范围", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        collections = BlogCollection.objects.filter(
            workspace_key=workspace_key, archived_at__isnull=True, published_snapshot__isnull=False
        ).order_by("-updated_at", "-id")
        if query:
            collections = collections.filter(Q(published_snapshot__title__icontains=query) | Q(title__icontains=query))
        total = collections.count()
        items = collections[(page - 1) * page_size : (page - 1) * page_size + page_size]
        # 批量解析本页全部文章 ID：单条查询判定可见性，避免逐领域 N+1。
        all_ids: list[int] = []
        snapshots = []
        for collection in items:
            snapshot = collection.published_snapshot or {}
            snapshots.append((collection, snapshot))
            all_ids.extend(entry["article"] for entry in snapshot.get("entries", []))
        visible = published_visible_articles(workspace_key, all_ids)
        results = []
        for collection, snapshot in snapshots:
            snapshot_ids = {entry["article"] for entry in snapshot.get("entries", [])}
            results.append(
                {
                    "public_id": str(collection.public_id),
                    "title": snapshot.get("title", collection.title),
                    "description": snapshot.get("description", ""),
                    "visible_article_count": len(snapshot_ids & visible.keys()),
                    "node_count": len(snapshot.get("nodes", [])),
                    "publication_version": collection.publication_version,
                    "updated_at": collection.updated_at.isoformat(),
                }
            )
        return Response(
            {
                "items": results,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": math.ceil(total / page_size),
            }
        )


class BlogCollectionPublicDetailView(APIView):
    """GET /blog/collections/<uuid>/ —— 已批准快照的树与当前可见文章。"""

    authentication_classes = []
    permission_classes = []

    def get(self, request, public_id):
        workspace_key = get_workspace_key(request)
        collection = (
            BlogCollection.objects.filter(
                public_id=str(public_id), workspace_key=workspace_key, archived_at__isnull=True
            )
            .exclude(published_snapshot__isnull=True)
            .first()
        )
        if collection is None:
            return error_response("领域不存在或尚未公开", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        snapshot = collection.published_snapshot or {}
        article_map = published_visible_articles(
            workspace_key, [entry["article"] for entry in snapshot.get("entries", [])]
        )
        children: dict[int | None, list[dict]] = {}
        for node in snapshot.get("nodes", []):
            children.setdefault(node["parent"], []).append(node)
        entries_by_node: dict[int | None, list[dict]] = {}
        for entry in snapshot.get("entries", []):
            if entry["article"] in article_map:
                entries_by_node.setdefault(entry["node"], []).append(entry)

        def serialize_node(node: dict, path: list[dict]) -> dict:
            next_path = [*path, {"id": node["id"], "title": node["title"]}]
            node_entries = sorted(entries_by_node.get(node["id"], []), key=lambda item: (item["position"], item["id"]))
            serialized = {
                "id": node["id"],
                "title": node["title"],
                "description": node["description"],
                "article_count": len(node_entries),
                "articles": [serialize_public_article(article_map[entry["article"]]) for entry in node_entries],
                "breadcrumb": next_path,
                "children": [
                    serialize_node(child, next_path)
                    for child in sorted(children.get(node["id"], []), key=lambda item: (item["position"], item["id"]))
                ],
            }
            return serialized

        root_entries = sorted(entries_by_node.get(None, []), key=lambda item: (item["position"], item["id"]))
        return Response(
            {
                "public_id": str(collection.public_id),
                "title": snapshot.get("title", collection.title),
                "description": snapshot.get("description", ""),
                "publication_version": collection.publication_version,
                "updated_at": collection.updated_at.isoformat(),
                "root_articles": [serialize_public_article(article_map[entry["article"]]) for entry in root_entries],
                "nodes": [
                    serialize_node(node, [])
                    for node in sorted(children.get(None, []), key=lambda item: (item["position"], item["id"]))
                ],
            }
        )


class BlogCollectionContextView(APIView):
    """GET /blog/collections/context/?article=<id>&collection=<uuid> —— 文章的目录上下文与前后篇。

    一篇文章属于多个领域时，优先使用读者来源的 collection 参数；
    否则取最近更新的公开领域。无效上下文返回 404，不影响正常阅读。
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        workspace_key = get_workspace_key(request)
        try:
            article_id = int(request.query_params.get("article", ""))
        except (TypeError, ValueError):
            return error_response("文章 ID 无效", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        requested_collection = str(request.query_params.get("collection", "")).strip()
        candidates = BlogCollection.objects.filter(
            workspace_key=workspace_key, archived_at__isnull=True, published_snapshot__isnull=False
        ).order_by("updated_at")
        if requested_collection:
            candidates = candidates.filter(public_id=requested_collection)
        for collection in candidates:
            snapshot = collection.published_snapshot or {}
            sequence = collection_reading_sequence(snapshot)
            index = next(
                (position for position, item in enumerate(sequence) if item["entry"]["article"] == article_id), None
            )
            if index is None:
                continue
            visible = published_visible_articles(workspace_key, [item["entry"]["article"] for item in sequence])
            if article_id not in visible:
                return error_response("该文章已不在公开目录中", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)

            def neighbor(offset: int, sequence=sequence, visible=visible, index=index):
                position = index + offset
                while 0 <= position < len(sequence):
                    item = sequence[position]
                    article = visible.get(item["entry"]["article"])
                    if article is not None:
                        return {
                            "slug": article.slug,
                            "title": article.title,
                            "node_path": [node["title"] for node in item["path"]],
                        }
                    position += offset
                return None

            current_item = sequence[index]
            return Response(
                {
                    "collection": {
                        "public_id": str(collection.public_id),
                        "title": snapshot.get("title", collection.title),
                    },
                    "node_path": [node["title"] for node in current_item["path"]],
                    "node_id": current_item["path"][-1]["id"] if current_item["path"] else None,
                    "prev": neighbor(-1),
                    "next": neighbor(1),
                }
            )
        return error_response("该文章不在公开目录中", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)


# --------------------------------------------------------------------------- 归档导出 / 导入（B-067）


def _zip_response(payload: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(payload, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Content-Length"] = str(len(payload))
    return response


class BlogCollectionExportView(APIView):
    """GET /blog/collections/<uuid>/export/ —— 导出单个领域（含图片）。"""

    authentication_classes = []
    permission_classes = []

    def get(self, request, public_id):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        collection = _get_owned_collection(public_id, principal)
        if collection is None:
            return error_response("领域不存在", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        try:
            payload, stats = build_archive_bytes([collection])
        except ArchiveError as exc:
            return error_response(str(exc), ErrorCode.VALIDATION_ERROR, exc.http_status)
        response = _zip_response(payload, export_filename([collection]))
        response["X-Archive-Images"] = str(stats["images"])
        response["X-Archive-Articles"] = str(stats["articles"])
        return response


class BlogCollectionBulkExportView(APIView):
    """GET /blog/collections/export/?ids=<uuid>,<uuid> —— 批量导出多个领域。"""

    authentication_classes = []
    permission_classes = []
    MAX_EXPORT = 20

    def get(self, request):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        raw = str(request.query_params.get("ids", "") or "")
        keys = [part.strip() for part in raw.split(",") if part.strip()]
        if not keys:
            return error_response("请选择要导出的领域", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)
        if len(keys) > self.MAX_EXPORT:
            return error_response(
                f"一次最多导出 {self.MAX_EXPORT} 个领域", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )
        user, workspace_key = principal
        collections = list(
            BlogCollection.objects.filter(
                public_id__in=keys, owner=user, workspace_key=workspace_key, archived_at__isnull=True
            ).order_by("title", "id")
        )
        if not collections:
            return error_response("没有可导出的领域", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
        try:
            payload, stats = build_archive_bytes(collections)
        except ArchiveError as exc:
            return error_response(str(exc), ErrorCode.VALIDATION_ERROR, exc.http_status)
        response = _zip_response(payload, export_filename(collections))
        response["X-Archive-Collections"] = str(stats["collections"])
        response["X-Archive-Images"] = str(stats["images"])
        return response


class BlogCollectionImportView(APIView):
    """POST /blog/collections/import/ —— 预览或导入领域导出包。"""

    authentication_classes = []
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        principal = collection_principal(request)
        if principal is None:
            return error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
        user, workspace_key = principal
        denied = _check_write_rate(user)
        if denied:
            return denied
        upload = request.FILES.get("file")
        if upload is None:
            return error_response("请选择导出的 zip 包", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)
        if upload.size and upload.size > MAX_ARCHIVE_BYTES:
            return error_response(
                "压缩包不能超过 200 MiB", ErrorCode.VALIDATION_ERROR, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )
        mode = str(request.data.get("mode", "preview")).strip().lower()
        conflict = str(request.data.get("conflict", CONFLICT_SKIP)).strip().lower()
        try:
            payload, files = read_archive(upload)
            if mode == "preview":
                return Response({"mode": "preview", **plan_import(payload, files, workspace_key=workspace_key, owner=user)})
            if mode != "apply":
                return error_response("mode 只能是 preview 或 apply", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
            result = apply_import(payload, files, owner=user, workspace_key=workspace_key, conflict=conflict)
        except ArchiveError as exc:
            return error_response(str(exc), ErrorCode.VALIDATION_ERROR, exc.http_status)
        return Response({"mode": "apply", "conflict": conflict, **result}, status=status.HTTP_201_CREATED)
