"""B-065 领域目录：文章批量加入 + 分类自动收录规则。"""

import json

from django.test import TestCase

from ..models import ArticleCategory, ArticleTag, BlogArticle, BlogCollection, BlogCollectionEntry
from .support import VisitorApiTestCase

COLLECTIONS_BASE = "/api/agent/blog/collections/"


def published_article(title: str, *, category=None, tags=None, workspace_key="default"):
    article = BlogArticle.objects.create(
        title=title,
        workspace_key=workspace_key,
        slug=f"post-{BlogArticle.objects.count()}-{title}",
        author_name="author",
        content=f"# {title}\n\n正文。",
        status=BlogArticle.Status.PUBLISHED,
        category=category,
    )
    if tags:
        article.tags.set(tags)
    return article


class BatchEntryTests(VisitorApiTestCase):
    def setUp(self):
        super().setUp()
        created = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "批量加入"}), content_type="application/json", HTTP_HOST="localhost"
        )
        self.public_id = created.json()["public_id"]
        self.articles = [published_article(f"文章{i}") for i in range(3)]

    def _version(self):
        draft = self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/draft/", HTTP_HOST="localhost")
        return draft.json()["draft_version"]

    def _add(self, payload):
        return self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/entries/",
            json.dumps(payload),
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def test_batch_add_multiple_articles(self):
        response = self._add(
            {
                "article_ids": [article.pk for article in self.articles],
                "expected_version": self._version(),
            }
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["added"], 3)
        self.assertEqual(body["skipped"], [])
        self.assertEqual(len(body["entries"]), 3)
        self.assertEqual(BlogCollectionEntry.objects.filter(collection__public_id=self.public_id).count(), 3)

    def test_batch_add_positions_are_sequential(self):
        self._add({"article_ids": [article.pk for article in self.articles], "expected_version": self._version()})
        positions = sorted(
            BlogCollectionEntry.objects.filter(collection__public_id=self.public_id).values_list("position", flat=True)
        )
        self.assertEqual(positions, [0, 1, 2])

    def test_duplicate_articles_are_skipped(self):
        self._add({"article_ids": [self.articles[0].pk, self.articles[1].pk], "expected_version": self._version()})
        again = self._add(
            {"article_ids": [article.pk for article in self.articles], "expected_version": self._version()}
        )
        self.assertEqual(again.status_code, 201)
        self.assertEqual(again.json()["added"], 1)
        self.assertEqual(sorted(again.json()["skipped"]), sorted([self.articles[0].pk, self.articles[1].pk]))

    def test_fully_duplicated_batch_conflicts(self):
        self._add({"article_ids": [self.articles[0].pk], "expected_version": self._version()})
        again = self._add({"article_ids": [self.articles[0].pk], "expected_version": self._version()})
        self.assertEqual(again.status_code, 409)

    def test_single_article_id_still_supported(self):
        response = self._add({"article_id": self.articles[0].pk, "expected_version": self._version()})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["added"], 1)
        self.assertEqual(response.json()["entry"]["article_id"], self.articles[0].pk)

    def test_draft_article_rejected(self):
        draft = BlogArticle.objects.create(
            title="草稿",
            workspace_key="default",
            slug="draft-batch",
            content="draft",
            status=BlogArticle.Status.DRAFT,
        )
        response = self._add({"article_ids": [draft.pk], "expected_version": self._version()})
        self.assertEqual(response.status_code, 400)

    def test_empty_selection_rejected(self):
        response = self._add({"article_ids": [], "expected_version": self._version()})
        self.assertEqual(response.status_code, 400)

    def test_batch_size_limit(self):
        response = self._add(
            {"article_ids": list(range(1, 60)), "expected_version": self._version()}
        )
        self.assertEqual(response.status_code, 400)

    def test_expected_version_conflict(self):
        response = self._add({"article_ids": [self.articles[0].pk], "expected_version": 999})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(BlogCollectionEntry.objects.filter(collection__public_id=self.public_id).count(), 0)


class AutoRuleTests(VisitorApiTestCase):
    def setUp(self):
        super().setUp()
        created = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "自动收录"}), content_type="application/json", HTTP_HOST="localhost"
        )
        self.public_id = created.json()["public_id"]
        self.category = ArticleCategory.objects.create(name="算法", slug="algo-rules")
        self.other_category = ArticleCategory.objects.create(name="随笔", slug="essay-rules")
        self.node = self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/nodes/",
            json.dumps({"title": "第一章", "expected_version": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
        ).json()["node"]

    # --- helpers -----------------------------------------------------
    def _rule(self, payload):
        return self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/auto-rules/",
            json.dumps(payload),
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def _draft(self):
        return self.client.get(f"{COLLECTIONS_BASE}{self.public_id}/draft/", HTTP_HOST="localhost").json()

    def _entry_article_ids(self):
        return set(
            BlogCollectionEntry.objects.filter(collection__public_id=self.public_id).values_list("article_id", flat=True)
        )

    # --- tests -------------------------------------------------------
    def test_rule_collects_existing_articles_on_create(self):
        first = published_article("排序", category=self.category)
        second = published_article("图论", category=self.category)
        published_article("无关", category=self.other_category)

        response = self._rule({"node_id": self.node["id"], "category_id": self.category.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["added"], 2)
        self.assertEqual(self._entry_article_ids(), {first.pk, second.pk})
        entries = BlogCollectionEntry.objects.filter(collection__public_id=self.public_id)
        self.assertTrue(all(entry.node_id == self.node["id"] for entry in entries))

    def test_new_article_is_collected_on_next_draft_read(self):
        published_article("初始", category=self.category)
        self._rule({"node_id": self.node["id"], "category_id": self.category.pk})

        fresh = published_article("新发布", category=self.category)
        draft = self._draft()
        self.assertEqual(draft["auto_applied"], 1)
        self.assertIn(fresh.pk, self._entry_article_ids())

    def test_draft_read_is_idempotent(self):
        published_article("初始", category=self.category)
        self._rule({"node_id": self.node["id"], "category_id": self.category.pk})
        first_read = self._draft()
        second_read = self._draft()
        self.assertEqual(first_read["auto_applied"], 0)
        self.assertEqual(second_read["auto_applied"], 0)
        self.assertEqual(len(first_read["entries"]), len(second_read["entries"]))
        self.assertEqual(len(self._entry_article_ids()), 1)

    def test_disabled_rule_does_not_collect(self):
        published_article("初始", category=self.category)
        created = self._rule({"node_id": self.node["id"], "category_id": self.category.pk})
        rule_id = created.json()["rule"]["id"]
        self.client.patch(
            f"{COLLECTIONS_BASE}{self.public_id}/auto-rules/{rule_id}/",
            json.dumps({"enabled": False}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        fresh = published_article("停用后发布", category=self.category)
        draft = self._draft()
        self.assertEqual(draft["auto_applied"], 0)
        self.assertNotIn(fresh.pk, self._entry_article_ids())

    def test_tag_narrows_the_rule(self):
        tag = ArticleTag.objects.create(name="动态规划", slug="dp-rules")
        tagged = published_article("背包", category=self.category, tags=[tag])
        untagged = published_article("贪心", category=self.category)
        self._rule({"node_id": self.node["id"], "category_id": self.category.pk, "tag_id": tag.pk})
        collected = self._entry_article_ids()
        self.assertIn(tagged.pk, collected)
        self.assertNotIn(untagged.pk, collected)

    def test_rule_can_target_collection_root(self):
        published_article("根文章", category=self.category)
        response = self._rule({"category_id": self.category.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["rule"]["node"], None)
        self.assertEqual(response.json()["rule"]["node_label"], "领域根")

    def test_category_is_required(self):
        response = self._rule({"node_id": self.node["id"]})
        self.assertEqual(response.status_code, 400)

    def test_duplicate_rule_rejected(self):
        self._rule({"node_id": self.node["id"], "category_id": self.category.pk})
        duplicate = self._rule({"node_id": self.node["id"], "category_id": self.category.pk})
        self.assertEqual(duplicate.status_code, 409)

    def test_rule_from_other_collection_node_rejected(self):
        other = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "别的领域"}), content_type="application/json", HTTP_HOST="localhost"
        ).json()["public_id"]
        foreign_node = self.client.post(
            f"{COLLECTIONS_BASE}{other}/nodes/",
            json.dumps({"title": "外来节点", "expected_version": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
        ).json()["node"]
        response = self._rule({"node_id": foreign_node["id"], "category_id": self.category.pk})
        self.assertEqual(response.status_code, 400)

    def test_delete_rule_stops_future_collection(self):
        published_article("初始", category=self.category)
        rule_id = self._rule({"node_id": self.node["id"], "category_id": self.category.pk}).json()["rule"]["id"]
        deleted = self.client.delete(
            f"{COLLECTIONS_BASE}{self.public_id}/auto-rules/{rule_id}/", HTTP_HOST="localhost"
        )
        self.assertEqual(deleted.status_code, 200)
        fresh = published_article("删除后发布", category=self.category)
        self._draft()
        self.assertNotIn(fresh.pk, self._entry_article_ids())

    def test_draft_payload_exposes_rules(self):
        self._rule({"node_id": self.node["id"], "category_id": self.category.pk})
        draft = self._draft()
        self.assertEqual(len(draft["auto_rules"]), 1)
        rule = draft["auto_rules"][0]
        self.assertEqual(rule["category"]["slug"], self.category.slug)
        self.assertEqual(rule["node_label"], "第一章")
        self.assertTrue(rule["enabled"])

    def test_manual_add_still_wins_over_rule_position(self):
        manual = published_article("手动先加入", category=self.category)
        self.client.post(
            f"{COLLECTIONS_BASE}{self.public_id}/entries/",
            json.dumps(
                {
                    "article_ids": [manual.pk],
                    "node_id": self.node["id"],
                    "expected_version": self._draft()["draft_version"],
                }
            ),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self._rule({"node_id": self.node["id"], "category_id": self.category.pk})
        self._draft()
        entries = BlogCollectionEntry.objects.filter(collection__public_id=self.public_id).order_by("position", "id")
        self.assertEqual(entries.first().article_id, manual.pk)


class AutoRuleIsolationTests(VisitorApiTestCase):
    def test_anonymous_cannot_manage_rules(self):
        created = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": "鉴权"}), content_type="application/json", HTTP_HOST="localhost"
        )
        public_id = created.json()["public_id"]
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        response = self.client.get(f"{COLLECTIONS_BASE}{public_id}/auto-rules/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 401)
        post = self.client.post(
            f"{COLLECTIONS_BASE}{public_id}/auto-rules/",
            json.dumps({"category_id": 1}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(post.status_code, 401)


class ApplyAutoRulesUnitTests(TestCase):
    """服务层纯逻辑：容量上限与工作区隔离。"""

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="rule-owner", password="pwd")
        self.collection = BlogCollection.objects.create(owner=self.user, title="单元", slug="unit-rules")
        self.category = ArticleCategory.objects.create(name="单元分类", slug="unit-category")

    def test_respects_max_entries_cap(self):
        from ..models import BlogCollectionAutoRule
        from ..services import blog_collections as service

        for index in range(3):
            published_article(f"批量{index}", category=self.category)
        BlogCollectionAutoRule.objects.create(collection=self.collection, category=self.category)
        # 人为压低上限，验证不会无限灌入
        original = service.MAX_ENTRIES
        service.MAX_ENTRIES = 2
        try:
            result = service.apply_auto_rules(self.collection)
        finally:
            service.MAX_ENTRIES = original
        self.assertEqual(result["added"], 2)
        self.assertEqual(BlogCollectionEntry.objects.filter(collection=self.collection).count(), 2)

    def test_other_workspace_articles_are_ignored(self):
        from ..models import BlogCollectionAutoRule
        from ..services.blog_collections import apply_auto_rules

        published_article("同空间", category=self.category, workspace_key="default")
        published_article("外空间", category=self.category, workspace_key="elsewhere")
        BlogCollectionAutoRule.objects.create(collection=self.collection, category=self.category)
        apply_auto_rules(self.collection)
        titles = set(
            BlogCollectionEntry.objects.filter(collection=self.collection).values_list("article__title", flat=True)
        )
        self.assertEqual(titles, {"同空间"})
