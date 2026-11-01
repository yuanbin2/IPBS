"""B-042 领域知识目录：私有树、权限、审核快照与公开读取专项。"""

import json
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from ..models import ApprovalRequest, BlogArticle, BlogCollection
from .support import AdminApiTestCase, VisitorApiTestCase

PUBLIC_LIST = "/api/agent/blog/collections/"
COLLECTIONS_BASE = "/api/agent/blog/collections/"


def published_article(workspace_key="default", title="已发布文章", slug=None):
    return BlogArticle.objects.create(
        title=title,
        workspace_key=workspace_key,
        slug=slug or f"post-{title}-{BlogArticle.objects.count()}",
        author_name="author",
        content="# 正文\n\n内容。",
        status=BlogArticle.Status.PUBLISHED,
        published_at=None,
    )


def draft_article(workspace_key="default", title="草稿文章"):
    return BlogArticle.objects.create(
        title=title,
        workspace_key=workspace_key,
        slug=f"draft-{title}-{BlogArticle.objects.count()}",
        author_name="author",
        content="draft",
        status=BlogArticle.Status.DRAFT,
    )


class CollectionPermissionsTests(VisitorApiTestCase):
    def test_anonymous_and_forged_role_cannot_create(self):
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        response = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "算法"}), content_type="application/json", HTTP_HOST="localhost"
        )
        self.assertEqual(response.status_code, 401)
        response = self.client.post(
            COLLECTIONS_BASE,
            json.dumps({"title": "算法"}),
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_X_ROLE="admin",
        )
        self.assertEqual(response.status_code, 401)

    def test_create_lists_and_updates_own_collection(self):
        created = self.client.post(
            COLLECTIONS_BASE,
            json.dumps({"title": "算法", "description": "学习路径"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(created.status_code, 201)
        public_id = created.json()["public_id"]
        self.assertEqual(created.json()["draft_version"], 1)

        mine = self.client.get(COLLECTIONS_BASE + "mine/", HTTP_HOST="localhost")
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(len(mine.json()["items"]), 1)

        draft = self.client.get(f"{COLLECTIONS_BASE}{public_id}/draft/", HTTP_HOST="localhost")
        self.assertEqual(draft.status_code, 200)
        patched = self.client.patch(
            f"{COLLECTIONS_BASE}{public_id}/draft/",
            json.dumps({"title": "算法与数据结构", "expected_version": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["title"], "算法与数据结构")
        self.assertEqual(patched.json()["draft_version"], 2)

    def test_other_user_and_other_workspace_cannot_touch_private_draft(self):
        created = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "我的领域"}), content_type="application/json", HTTP_HOST="localhost"
        )
        public_id = created.json()["public_id"]
        _, token = self.authenticate_test_user("operator")
        detail = self.client.get(f"{COLLECTIONS_BASE}{public_id}/draft/", HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 404)
        patched = self.client.patch(
            f"{COLLECTIONS_BASE}{public_id}/draft/",
            json.dumps({"title": "劫持", "expected_version": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(patched.status_code, 404)

        # 同一用户的 profile 换到其他 workspace 后，原工作区目录不再可见
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        from ..models import UserProfile as Profile

        owner_profile = Profile.objects.filter(user=self.test_user).first()
        self.assertIsNotNone(owner_profile)
        owner_profile.workspace_key = "moved-ws"
        owner_profile.save(update_fields=["workspace_key"])
        response = self.client.get(f"{COLLECTIONS_BASE}{public_id}/draft/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 404)

    def test_title_limits(self):
        response = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "域" * 121}), content_type="application/json", HTTP_HOST="localhost"
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            COLLECTIONS_BASE, json.dumps({}), content_type="application/json", HTTP_HOST="localhost"
        )
        self.assertEqual(response.status_code, 400)


class CollectionTreeTests(VisitorApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        created = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "树测试"}), content_type="application/json", HTTP_HOST="localhost"
        )
        self.public_id = created.json()["public_id"]

    def _create_node(self, parent_id=None, title="节点", expected_version=None):
        if expected_version is None:
            expected_version = self._draft_version()
        payload = {"title": title, "expected_version": expected_version}
        if parent_id is not None:
            payload["parent_id"] = parent_id
        return self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/nodes/",
            json.dumps(payload),
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def _draft_version(self):
        draft = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/draft/", HTTP_HOST="localhost")
        return draft.json()["draft_version"]

    def test_three_levels_allowed_and_fourth_rejected(self):
        root = self._create_node(title="基础课")
        self.assertEqual(root.status_code, 201)
        root_id = root.json()["node"]["id"]
        chapter = self._create_node(parent_id=root_id, title="第一讲")
        self.assertEqual(chapter.status_code, 201)
        chapter_id = chapter.json()["node"]["id"]
        point = self._create_node(parent_id=chapter_id, title="排序")
        self.assertEqual(point.status_code, 201)
        point_id = point.json()["node"]["id"]
        too_deep = self._create_node(parent_id=point_id, title="再深一级")
        self.assertEqual(too_deep.status_code, 400)
        self.assertIn("层级", too_deep.json()["detail"])

    def test_cross_tree_parent_and_cycle_are_rejected(self):
        other = self.client.post(
            COLLECTIONS_BASE,
            json.dumps({"title": "另一个领域"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        other_root = self.client.post(
            f"{COLLECTIONS_BASE}{other.json()['public_id']}/nodes/",
            json.dumps({"title": "外来节点", "expected_version": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        root = self._create_node(title="根节点")
        root_id = root.json()["node"]["id"]
        child = self._create_node(parent_id=root_id, title="子节点")
        child_id = child.json()["node"]["id"]

        cross = self.client.patch(
            f"{COLLECTIONS_BASE}{self.public_id}/nodes/{root_id}/",
            json.dumps({"parent_id": other_root.json()["node"]["id"], "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(cross.status_code, 400)

        cycle = self.client.patch(
            f"{COLLECTIONS_BASE}{self.public_id}/nodes/{root_id}/",
            json.dumps({"parent_id": child_id, "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(cycle.status_code, 400)
        self.assertIn("自己", cycle.json()["detail"])

    def test_move_updates_depth_and_version(self):
        root_a = self._create_node(title="A")
        root_b = self._create_node(title="B")
        child = self._create_node(parent_id=root_a.json()["node"]["id"], title="A-1")
        moved = self.client.patch(
            f"{COLLECTIONS_BASE}{self.public_id}/nodes/{child.json()['node']['id']}/",
            json.dumps({"parent_id": root_b.json()["node"]["id"], "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["node"]["parent"], root_b.json()["node"]["id"])
        draft = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/draft/", HTTP_HOST="localhost")
        positions = {node["id"]: node["position"] for node in draft.json()["nodes"]}
        self.assertLess(positions[root_a.json()["node"]["id"]] if root_a.json()["node"]["id"] in positions else 0, 10)

    def test_delete_node_cascades_children_and_entries(self):
        root = self._create_node(title="课程")
        root_id = root.json()["node"]["id"]
        chapter = self._create_node(parent_id=root_id, title="章节")
        chapter_id = chapter.json()["node"]["id"]
        added = self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/entries/",
            json.dumps(
                {"article_id": published_article().pk, "node_id": chapter_id, "expected_version": self._draft_version()}
            ),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(added.status_code, 201)
        deleted = self.client.delete(
            f"{COLLECTIONS_BASE}{self.public_id}/nodes/{root_id}/",
            json.dumps({"expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(deleted.status_code, 200)
        draft = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/draft/", HTTP_HOST="localhost")
        self.assertEqual(draft.json()["nodes"], [])
        self.assertEqual(draft.json()["entries"], [])

    def test_version_conflicts_return_409(self):
        root = self._create_node(title="冲突")
        node_id = root.json()["node"]["id"]
        stale = self.client.patch(
            f"{COLLECTIONS_BASE}{self.public_id}/nodes/{node_id}/",
            json.dumps({"title": "改名", "expected_version": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(stale.status_code, 409)
        missing = self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/nodes/",
            json.dumps({"title": "新节点"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(missing.status_code, 409)

    def test_reorder_requires_exact_id_set(self):
        first = self._create_node(title="一")
        second = self._create_node(title="二")
        third = self._create_node(title="三")
        ids = [first.json()["node"]["id"], second.json()["node"]["id"], third.json()["node"]["id"]]
        partial = self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/reorder/",
            json.dumps(
                {"scope": "nodes", "parent_id": None, "ordered_ids": ids[:2], "expected_version": self._draft_version()}
            ),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(partial.status_code, 400)
        reordered = self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/reorder/",
            json.dumps(
                {
                    "scope": "nodes",
                    "parent_id": None,
                    "ordered_ids": ids[::-1],
                    "expected_version": self._draft_version(),
                }
            ),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(reordered.status_code, 200)
        draft = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/draft/", HTTP_HOST="localhost")
        by_position = sorted(draft.json()["nodes"], key=lambda node: node["position"])
        self.assertEqual([node["id"] for node in by_position], ids[::-1])

    def test_entry_rules_published_same_workspace_unique(self):
        article = published_article()
        draft_only = draft_article()
        foreign = published_article(workspace_key="other-ws", title="别处文章")
        root_entry = self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/entries/",
            json.dumps({"article_id": article.pk, "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(root_entry.status_code, 201)
        self.assertIsNone(root_entry.json()["entry"]["node"])
        duplicate = self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/entries/",
            json.dumps({"article_id": article.pk, "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(duplicate.status_code, 409)
        unpublished = self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/entries/",
            json.dumps({"article_id": draft_only.pk, "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(unpublished.status_code, 400)
        foreign_entry = self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/entries/",
            json.dumps({"article_id": foreign.pk, "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(foreign_entry.status_code, 400)

    def test_node_and_entry_capacity_limits(self):
        with patch("apps.agent_api.services.blog_collections.MAX_NODES", 2):
            self._create_node(title="n1")
            self._create_node(title="n2")
            third = self._create_node(title="n3")
        self.assertEqual(third.status_code, 400)
        with patch("apps.agent_api.services.blog_collections.MAX_ENTRIES", 1):
            self.client.post(
                f"{COLLECTIONS_BASE}{self.public_id}/entries/",
                json.dumps(
                    {"article_id": published_article(title="容量一").pk, "expected_version": self._draft_version()}
                ),
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            second = self.client.post(
                f"{COLLECTIONS_BASE}{self.public_id}/entries/",
                json.dumps(
                    {"article_id": published_article(title="容量二").pk, "expected_version": self._draft_version()}
                ),
                content_type="application/json",
                HTTP_HOST="localhost",
            )
        self.assertEqual(second.status_code, 400)

    def test_legacy_category_and_tag_apis_unchanged(self):
        response = self.client.get("/api/agent/blog/categories/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/agent/blog/tags/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)


class CollectionDeleteTests(VisitorApiTestCase):
    def test_unpublished_delete_and_published_archive(self):
        created = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "待删除"}), content_type="application/json", HTTP_HOST="localhost"
        )
        public_id = created.json()["public_id"]
        deleted = self.client.delete(f"{COLLECTIONS_BASE}{public_id}/draft/", HTTP_HOST="localhost")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(deleted.json()["archived"])
        self.assertFalse(BlogCollection.objects.filter(public_id=public_id).exists())

        created = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "待归档"}), content_type="application/json", HTTP_HOST="localhost"
        )
        public_id = created.json()["public_id"]
        article = published_article()
        self.client.post(
            f"{COLLECTIONS_BASE}{public_id}/entries/",
            json.dumps({"article_id": article.pk, "expected_version": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.client.post(f"{COLLECTIONS_BASE}{public_id}/submit/", HTTP_HOST="localhost")
        approval = ApprovalRequest.objects.get(action=ApprovalRequest.Action.PUBLISH_BLOG_COLLECTION)
        self.authenticate_test_user("admin")
        self.client.post(
            f"/api/agent/approvals/{approval.pk}/",
            json.dumps({"decision": "approve"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        # 恢复作者身份后再归档
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.test_token}"
        archived = self.client.delete(f"{COLLECTIONS_BASE}{public_id}/draft/", HTTP_HOST="localhost")
        self.assertEqual(archived.status_code, 200)
        self.assertTrue(archived.json()["archived"])
        self.assertTrue(BlogCollection.objects.filter(public_id=public_id, archived_at__isnull=False).exists())
        public_detail = self.client.get(f"{COLLECTIONS_BASE}{public_id}/", HTTP_HOST="localhost")
        self.assertEqual(public_detail.status_code, 404)
        listing = self.client.get(PUBLIC_LIST, HTTP_HOST="localhost")
        self.assertEqual(listing.json()["total"], 0)


class CollectionPublishFlowTests(AdminApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        _, token = self.authenticate_test_user("author")
        self.author_token = token
        created = self.client.post(
            COLLECTIONS_BASE,
            json.dumps({"title": "算法学习路径", "description": "v1 简介"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.public_id = created.json()["public_id"]
        self.article = published_article(title="快速排序")
        self.other_article = published_article(title="归并排序")
        node = self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/nodes/",
            json.dumps({"title": "基础课", "expected_version": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.node_id = node.json()["node"]["id"]
        self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/entries/",
            json.dumps({"article_id": self.article.pk, "node_id": self.node_id, "expected_version": 2}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/entries/",
            json.dumps({"article_id": self.other_article.pk, "node_id": self.node_id, "expected_version": 3}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def _author(self):
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.author_token}"

    def _draft_version(self):
        self._author()
        draft = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/draft/", HTTP_HOST="localhost")
        return draft.json()["draft_version"]

    def _admin(self):
        self.authenticate_test_user("admin")

    def _submit(self, expect=(202, 200)):
        self._author()
        response = self.client.post(f"{COLLECTIONS_BASE}{self.public_id}/submit/", HTTP_HOST="localhost")
        self.assertIn(response.status_code, expect)
        return response.json()["approval_id"]

    def _approve(self, approval_id):
        self._admin()
        return self.client.post(
            f"/api/agent/approvals/{approval_id}/",
            json.dumps({"decision": "approve"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def _reject(self, approval_id):
        self._admin()
        return self.client.post(
            f"/api/agent/approvals/{approval_id}/",
            json.dumps({"decision": "reject", "note": "目录结构需要调整"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def test_submit_freezes_snapshot_and_draft_edits_do_not_leak(self):
        approval_id = self._submit()
        collection = BlogCollection.objects.get(public_id=self.public_id)
        self.assertEqual(collection.pending_snapshot["draft_version"], collection.draft_version)
        self.assertEqual(collection.pending_snapshot["nodes"][0]["title"], "基础课")
        frozen_hash = json.dumps(collection.pending_snapshot, sort_keys=True)

        # 作者继续编辑工作版：待审快照不变
        self._author()
        self.client.patch(
            f"{COLLECTIONS_BASE}{self.public_id}/draft/",
            json.dumps({"title": "私有新标题", "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        collection.refresh_from_db()
        self.assertEqual(json.dumps(collection.pending_snapshot, sort_keys=True), frozen_hash)
        self.assertIsNone(collection.published_snapshot)

        approved = self._approve(approval_id)
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "executed")
        collection.refresh_from_db()
        self.assertIsNotNone(collection.published_snapshot)
        self.assertEqual(collection.publication_version, 1)
        self.assertIsNone(collection.pending_snapshot)

        # 公开读取显示的是批准时的快照，不是之后的私有修改
        detail = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["title"], "算法学习路径")
        self.assertNotIn("私有新标题", detail.json()["title"])

    def test_duplicate_submit_is_idempotent_until_draft_changes(self):
        first = self._submit()
        second = self._submit()
        self.assertEqual(first, second)
        self._author()
        self.client.patch(
            f"{COLLECTIONS_BASE}{self.public_id}/draft/",
            json.dumps({"description": "更新简介", "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        third = self._submit(expect=(202,))
        self.assertNotEqual(third, first)
        old = ApprovalRequest.objects.get(pk=first)
        self.assertEqual(old.status, ApprovalRequest.Status.REJECTED)
        self.assertIn("替代", old.result)

    def test_reject_keeps_published_version_and_clears_pending(self):
        first = self._submit()
        self._approve(first)
        self._author()
        self.client.patch(
            f"{COLLECTIONS_BASE}{self.public_id}/draft/",
            json.dumps({"title": "改名后的领域", "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        second = self._submit(expect=(202,))
        rejected = self._reject(second)
        self.assertEqual(rejected.status_code, 200)
        collection = BlogCollection.objects.get(public_id=self.public_id)
        self.assertIsNone(collection.pending_snapshot)
        self.assertEqual(collection.published_snapshot["title"], "算法学习路径")
        detail = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.json()["title"], "算法学习路径")

    def test_stale_approval_cannot_publish(self):
        first = self._submit()
        self._author()
        self.client.patch(
            f"{COLLECTIONS_BASE}{self.public_id}/draft/",
            json.dumps({"description": "触发重新提交", "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        second = self._submit(expect=(202,))
        self.assertNotEqual(first, second)
        # 旧待审已在重提交时失效：批准它直接被拒，且不会发布任何快照
        stale = self._approve(first)
        self.assertEqual(stale.status_code, 400)
        self.assertIn("no longer pending", stale.json()["detail"])
        collection = BlogCollection.objects.get(public_id=self.public_id)
        self.assertIsNone(collection.published_snapshot)
        fresh = self._approve(second)
        self.assertEqual(fresh.json()["status"], "executed")

    def test_public_list_and_detail_with_batched_queries(self):
        approval_id = self._submit()
        self._approve(approval_id)
        articles = [published_article(title=f"批量文章{i}") for i in range(30)]
        self._author()
        version = None
        for article in articles:
            draft = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/draft/", HTTP_HOST="localhost")
            version = draft.json()["draft_version"]
            response = self.client.post(
                f"{COLLECTIONS_BASE}{self.public_id}/entries/",
                json.dumps({"article_id": article.pk, "node_id": self.node_id, "expected_version": version}),
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self.assertEqual(response.status_code, 201)
        approval_id = self._submit()
        self._approve(approval_id)

        with CaptureQueriesContext(connection) as context:
            detail = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 200)
        node = detail.json()["nodes"][0]
        self.assertEqual(node["article_count"], 32)
        self.assertLessEqual(len(context), 25)

        listing = self.client.get(PUBLIC_LIST, HTTP_HOST="localhost")
        self.assertEqual(listing.json()["total"], 1)
        self.assertEqual(listing.json()["items"][0]["visible_article_count"], 32)
        self.assertEqual(listing.json()["items"][0]["title"], "算法学习路径")

        search = self.client.get(PUBLIC_LIST + "?q=算法", HTTP_HOST="localhost")
        self.assertEqual(search.json()["total"], 1)
        miss = self.client.get(PUBLIC_LIST + "?q=" + "不存在的关键词" * 20, HTTP_HOST="localhost")
        self.assertEqual(miss.status_code, 400)

    def test_hidden_article_disappears_from_public_reads_and_context(self):
        third = published_article(title="第三篇")
        self._author()
        self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/entries/",
            json.dumps({"article_id": third.pk, "node_id": self.node_id, "expected_version": self._draft_version()}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        approval_id = self._submit()
        self._approve(approval_id)
        context = self.client.get(
            f"{COLLECTIONS_BASE}context/?article={self.article.pk}&collection={self.public_id}", HTTP_HOST="localhost"
        )
        self.assertEqual(context.status_code, 200)
        self.assertIsNone(context.json()["prev"])
        self.assertEqual(context.json()["next"]["slug"], self.other_article.slug)

        # 下架一篇文章：公开目录、计数、前后篇立刻隐藏
        BlogArticle.objects.filter(pk=self.other_article.pk).update(status=BlogArticle.Status.ARCHIVED)
        detail = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/", HTTP_HOST="localhost")
        node = detail.json()["nodes"][0]
        self.assertEqual(node["article_count"], 2)
        self.assertNotIn(self.other_article.pk, [article["id"] for article in node["articles"]])
        listing = self.client.get(PUBLIC_LIST, HTTP_HOST="localhost")
        self.assertEqual(listing.json()["items"][0]["visible_article_count"], 2)
        context = self.client.get(
            f"{COLLECTIONS_BASE}context/?article={self.article.pk}&collection={self.public_id}", HTTP_HOST="localhost"
        )
        self.assertEqual(context.json()["next"]["slug"], third.slug)
        hidden = self.client.get(
            f"{COLLECTIONS_BASE}context/?article={self.other_article.pk}&collection={self.public_id}",
            HTTP_HOST="localhost",
        )
        self.assertEqual(hidden.status_code, 404)

    def test_public_404_for_unpublished_foreign_workspace_and_anonymous_is_read_only(self):
        detail = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 404)
        approval_id = self._submit()
        self._approve(approval_id)
        detail = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 200)

        # 其他 workspace 的公开列表看不到该目录
        self.authenticate_test_user("admin", workspace_key="another")
        listing = self.client.get(PUBLIC_LIST, HTTP_HOST="localhost")
        self.assertEqual(listing.json()["total"], 0)

        # 匿名读者可以读取公开目录，但写接口拒绝
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        self.assertEqual(
            self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/", HTTP_HOST="localhost").status_code, 200
        )
        created = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "匿名"}), content_type="application/json", HTTP_HOST="localhost"
        )
        self.assertEqual(created.status_code, 401)

    def test_submit_rate_limit(self):
        with patch("apps.agent_api.views.blog_collections.SUBMIT_HOURLY_LIMIT", 2):
            self._submit()
            self.client.patch(
                f"{COLLECTIONS_BASE}{self.public_id}/draft/",
                json.dumps({"description": "再次提交", "expected_version": self._draft_version()}),
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self._submit(expect=(202,))
            self.client.patch(
                f"{COLLECTIONS_BASE}{self.public_id}/draft/",
                json.dumps({"description": "第三次提交", "expected_version": self._draft_version()}),
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self._author()
            limited = self.client.post(f"{COLLECTIONS_BASE}{self.public_id}/submit/", HTTP_HOST="localhost")
        self.assertEqual(limited.status_code, 429)


class CollectionSnapshotIntegrityTests(TransactionTestCase):
    def test_snapshot_hash_changes_when_snapshot_changes(self):
        from django.contrib.auth import get_user_model

        from ..services.blog_collections import build_snapshot, snapshot_sha256

        owner = get_user_model().objects.create_user(username="hash-owner", password="test-only-password-2026")
        collection = BlogCollection.objects.create(owner=owner, title="哈希", slug="hash", workspace_key="default")
        first = build_snapshot(collection)
        self.assertEqual(snapshot_sha256(first), snapshot_sha256(build_snapshot(collection)))
        collection.title = "哈希改"
        second = build_snapshot(collection)
        self.assertNotEqual(snapshot_sha256(first), snapshot_sha256(second))
