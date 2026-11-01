"""B-066 发布兜底：未填封面时使用正文第一张图片。"""

import json

from django.test import TestCase

from ..models import ApprovalRequest, BlogArticle, BlogArticleRevision
from ..services.blog import fill_default_cover, first_image_url, is_safe_image_url
from ..views.common import execute_approval_request
from .support import AdminApiTestCase, VisitorApiTestCase

ARTICLES = "/api/agent/blog/articles/"


class FirstImageUrlTests(TestCase):
    def test_markdown_image(self):
        self.assertEqual(first_image_url("![封面](/media/blog/a.png)\n正文"), "/media/blog/a.png")

    def test_first_wins_between_markdown_and_html(self):
        self.assertEqual(
            first_image_url('![先](/media/blog/one.png)\n<img src="/media/blog/two.png">'),
            "/media/blog/one.png",
        )
        self.assertEqual(
            first_image_url('<img src="/media/blog/one.png">\n![后](/media/blog/two.png)'),
            "/media/blog/one.png",
        )

    def test_unsafe_and_empty_values(self):
        self.assertIsNone(first_image_url(""))
        self.assertIsNone(first_image_url("没有图片的正文"))
        self.assertIsNone(first_image_url("![x](data:image/png;base64,AAA)"))
        self.assertIsNone(first_image_url('<img src="javascript:alert(1)">'))
        self.assertFalse(is_safe_image_url("ftp://example.com/a.png"))
        self.assertTrue(is_safe_image_url("https://cdn.example.com/a.png"))


class FillDefaultCoverTests(TestCase):
    def test_fills_only_when_empty(self):
        article = BlogArticle.objects.create(
            title="t", slug="cover-a", content="![图](/media/blog/a.png)", status=BlogArticle.Status.DRAFT
        )
        self.assertEqual(fill_default_cover(article), "/media/blog/a.png")
        self.assertEqual(article.cover_image, "/media/blog/a.png")
        self.assertIsNone(fill_default_cover(article))

    def test_existing_cover_is_kept(self):
        article = BlogArticle.objects.create(
            title="t",
            slug="cover-b",
            content="![图](/media/blog/a.png)",
            cover_image="/media/blog/manual.png",
            status=BlogArticle.Status.DRAFT,
        )
        self.assertIsNone(fill_default_cover(article))
        self.assertEqual(article.cover_image, "/media/blog/manual.png")


class PublishCoverFallbackTests(VisitorApiTestCase):
    def setUp(self):
        super().setUp()
        self.content = "开头文字。\n\n![正文首图](/media/blog/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png)\n\n结尾。"

    def _create(self, cover=None, content=None):
        payload = {"title": "封面兜底", "content": content or self.content}
        if cover is not None:
            payload["cover_image"] = cover
        return self.client.post(
            ARTICLES, json.dumps(payload), content_type="application/json", HTTP_HOST="localhost"
        )

    def test_create_without_cover_uses_first_image(self):
        response = self._create()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["article"]["cover_image"], "/media/blog/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png")

    def test_explicit_cover_is_preserved(self):
        response = self._create(cover="/media/blog/manual.png")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["article"]["cover_image"], "/media/blog/manual.png")

    def test_no_image_leaves_cover_empty(self):
        response = self._create(content="纯文字正文，没有图片。")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["article"]["cover_image"], "")

    def test_approval_execution_fills_cover(self):
        """直接构造"封面为空的待发布文章"，审批通过后应自动补上正文首图。"""
        article = BlogArticle.objects.create(
            title="审批兜底",
            slug="cover-approval",
            workspace_key="default",
            author_name="author",
            content=self.content,
            status=BlogArticle.Status.DRAFT,
        )
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
            workspace_key="default",
            title="发布",
            payload={"article_slug": article.slug, "article_id": article.pk},
            requester="author",
        )
        execute_approval_request(approval)
        article.refresh_from_db()
        self.assertEqual(article.status, BlogArticle.Status.PUBLISHED)
        self.assertEqual(article.cover_image, "/media/blog/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png")

    def test_revision_without_cover_is_filled(self):
        article = BlogArticle.objects.create(
            title="修订兜底",
            slug="cover-revision",
            workspace_key="default",
            author_name="author",
            content="旧正文 ![旧](old.png)",
            cover_image="/media/blog/old.png",
            status=BlogArticle.Status.PUBLISHED,
            publication_version=1,
        )
        revision = BlogArticleRevision.objects.create(
            article=article,
            base_version=1,
            title="修订兜底",
            summary="",
            cover_image="",
            content=self.content,
        )
        self.assertEqual(fill_default_cover(revision), "/media/blog/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png")
        self.assertEqual(BlogArticleRevision.objects.get(pk=revision.pk).cover_image, "")


class AdminPublishCoverTests(AdminApiTestCase):
    def test_operator_publish_fills_cover(self):
        article = BlogArticle.objects.create(
            title="运营发布",
            slug="cover-operator",
            workspace_key="default",
            author_name="author",
            content="![首图](/media/blog/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png)",
            status=BlogArticle.Status.DRAFT,
        )
        created = self.client.post(
            f"{ARTICLES}{article.slug}/publish/",
            json.dumps({}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(created.status_code, 202)
        article.refresh_from_db()
        self.assertEqual(article.cover_image, "/media/blog/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png")
