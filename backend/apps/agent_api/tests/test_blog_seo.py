"""Direct HTML responses must reflect only the current public publication."""

from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import urlopen
from xml.etree import ElementTree

from django.test import LiveServerTestCase, TestCase, override_settings
from django.utils import timezone

from ..models import BlogArticle, BlogArticleRevision

INDEX = '<!doctype html><html><head><title>智能个人博客系统</title></head><body><div id="app"></div><script src="/assets/app.js"></script></body></html>'


class PublicArticleHtmlTests(TestCase):
    def setUp(self):
        self.frontend = TemporaryDirectory()
        self.addCleanup(self.frontend.cleanup)
        Path(self.frontend.name, "index.html").write_text(INDEX, encoding="utf-8")
        self.settings_override = override_settings(
            FRONTEND_DIST=Path(self.frontend.name),
            ALLOWED_HOSTS=["example.test", "localhost", "testserver"],
            SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.client.defaults["HTTP_X_FORWARDED_PROTO"] = "https"
        self.article = BlogArticle.objects.create(
            title="文章 <script>alert(1)</script>",
            slug="公开文章",
            summary="简介 <img src=x onerror=alert(1)> & 信息",
            content="**正文唯一标记**",
            cover_image=f"/media/blog/{'a' * 32}.png",
            status=BlogArticle.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_direct_html_has_public_metadata_and_escaped_first_paint(self):
        with self.assertNumQueries(1):
            response = self.client.get("/blog/公开文章/?share=1", HTTP_HOST="example.test")
        page = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("<title>文章 &lt;script&gt;alert(1)&lt;/script&gt;</title>", page)
        self.assertIn('name="description" content="简介 &amp; 信息"', page)
        self.assertIn('property="og:title"', page)
        self.assertIn('name="twitter:title"', page)
        self.assertIn('href="https://example.test/blog/%E5%85%AC%E5%BC%80%E6%96%87%E7%AB%A0/"', page)
        self.assertIn(f'content="https://example.test/media/blog/{"a" * 32}.png"', page)
        self.assertIn("<main", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("?share=1", page)

        self.article.cover_image = "javascript:alert(1)"
        self.article.save(update_fields=["cover_image", "updated_at"])
        unsafe_cover = self.client.get("/blog/公开文章/", HTTP_HOST="example.test")
        self.assertNotIn('property="og:image"', unsafe_cover.content.decode())

    def test_update_and_withdrawal_are_visible_without_rebuild(self):
        first = self.client.get("/blog/公开文章/", HTTP_HOST="example.test")
        self.assertIn("文章 &lt;script&gt;", first.content.decode())
        self.article.title = "更新后标题"
        self.article.summary = "更新后摘要"
        self.article.save(update_fields=["title", "summary", "updated_at"])
        refreshed = self.client.get("/blog/公开文章/", HTTP_HOST="example.test")
        self.assertIn("更新后标题", refreshed.content.decode())
        self.assertIn("更新后摘要", refreshed.content.decode())
        self.assertNotIn("文章 &lt;script&gt;", refreshed.content.decode())
        self.article.status = BlogArticle.Status.ARCHIVED
        self.article.save(update_fields=["status", "updated_at"])
        withdrawn = self.client.get("/blog/公开文章/", HTTP_HOST="example.test")
        self.assertEqual(withdrawn.status_code, 404)
        self.assertEqual(withdrawn["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn("更新后标题", withdrawn.content.decode())
        self.assertNotIn("更新后摘要", withdrawn.content.decode())

    def test_private_draft_other_workspace_and_pending_revision_never_enter_html(self):
        BlogArticle.objects.create(title="私密标题", slug="private", content="PRIVATE-MARKER")
        BlogArticle.objects.create(
            title="其他空间标题",
            slug="other-workspace",
            content="WORKSPACE-MARKER",
            workspace_key="other",
            status=BlogArticle.Status.PUBLISHED,
        )
        BlogArticleRevision.objects.create(
            article=self.article,
            base_version=1,
            title="待审核标题",
            summary="PENDING-SUMMARY",
            content="PENDING-CONTENT",
            submitted_by="operator",
            status=BlogArticleRevision.Status.PENDING,
        )
        for slug, marker in (("private", "PRIVATE-MARKER"), ("other-workspace", "WORKSPACE-MARKER")):
            response = self.client.get(f"/blog/{slug}/", HTTP_HOST="example.test")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
            self.assertNotIn(marker, response.content.decode())
            self.assertIn("/assets/app.js", response.content.decode())
        public = self.client.get("/blog/公开文章/", HTTP_HOST="example.test")
        self.assertNotIn("PENDING-SUMMARY", public.content.decode())
        self.assertNotIn("PENDING-CONTENT", public.content.decode())
        self.assertNotIn("待审核标题", public.content.decode())

    def test_non_article_routes_keep_static_spa_shell(self):
        for path in ("/blog/", "/blog/collections", "/blog/settings", "/blog/collections/example"):
            response = self.client.get(path, HTTP_HOST="example.test")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("data-blog-seo", b"".join(response.streaming_content).decode())
        robots = self.client.get("/robots.txt", HTTP_HOST="example.test")
        self.assertEqual(robots.status_code, 200)
        self.assertIn("User-agent: *", robots.content.decode())
        self.assertIn("Sitemap: https://example.test/sitemap.xml", robots.content.decode())

    def test_sitemap_tracks_only_current_public_articles(self):
        private = BlogArticle.objects.create(title="Private", slug="private-sitemap", content="secret")
        other = BlogArticle.objects.create(
            title="Other",
            slug="other-sitemap",
            content="other",
            workspace_key="other",
            status=BlogArticle.Status.PUBLISHED,
        )
        response = self.client.get("/sitemap.xml", HTTP_HOST="example.test")
        xml = response.content.decode()
        ElementTree.fromstring(xml)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("https://example.test/blog/%E5%85%AC%E5%BC%80%E6%96%87%E7%AB%A0/", xml)
        self.assertNotIn(private.slug, xml)
        self.assertNotIn(other.slug, xml)
        self.article.status = BlogArticle.Status.ARCHIVED
        self.article.save(update_fields=["status", "updated_at"])
        self.assertNotIn(
            "%E5%85%AC%E5%BC%80%E6%96%87%E7%AB%A0",
            self.client.get("/sitemap.xml", HTTP_HOST="example.test").content.decode(),
        )


class PublicArticleHttpSmokeTests(LiveServerTestCase):
    def setUp(self):
        self.frontend = TemporaryDirectory()
        self.addCleanup(self.frontend.cleanup)
        Path(self.frontend.name, "index.html").write_text(INDEX, encoding="utf-8")
        self.settings_override = override_settings(FRONTEND_DIST=Path(self.frontend.name))
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def test_direct_http_update_and_withdrawal(self):
        article = BlogArticle.objects.create(
            title="HTTP 直达标题",
            slug="http-fixture",
            summary="HTTP 首包摘要",
            content="HTTP 正文",
            status=BlogArticle.Status.PUBLISHED,
        )
        url = f"{self.live_server_url}/blog/http-fixture/"
        with urlopen(url, timeout=5) as response:
            page = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertIn("HTTP 直达标题", page)
            self.assertIn("HTTP 首包摘要", page)
            self.assertIn(f'<link data-blog-seo rel="canonical" href="{url}">', page)
        article.status = BlogArticle.Status.ARCHIVED
        article.save(update_fields=["status", "updated_at"])
        with self.assertRaises(HTTPError) as failure:
            urlopen(url, timeout=5)
        self.assertEqual(failure.exception.code, 404)
        self.assertEqual(failure.exception.headers["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn("HTTP 首包摘要", failure.exception.read().decode("utf-8"))
