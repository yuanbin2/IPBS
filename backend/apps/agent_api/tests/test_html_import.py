"""HTML import is a preview-only, authenticated conversion boundary."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from ..models import BlogArticle
from ..services.html_import import HtmlImportError, convert_html_to_markdown
from .support import VisitorApiTestCase


class HtmlImportServiceTests(TestCase):
    def test_semantic_article_excludes_navigation_and_preserves_structure(self):
        html = """
        <html><head><title>Site title</title></head><body>
          <nav><a href='/'>Home</a><a href='/ads'>Ads</a></nav>
          <article><h1>真正标题</h1><p>第一段正文，包含 <strong>重点</strong>。</p>
          <h2>实现</h2><p>第二段正文和 <a href='/source'>来源</a>。</p>
          <pre><code class='language-python'>print('ok')\n```</code></pre>
          <table><tr><th>字段</th><th>说明</th></tr><tr><td>ID</td><td>编号</td></tr></table>
          </article><footer>版权信息</footer><script>window.steal()</script>
        </body></html>"""
        result = convert_html_to_markdown(html.encode(), filename="page.html", source_url="https://example.org/post")
        markdown = result["content_markdown"]
        self.assertEqual(result["title"], "真正标题")
        self.assertIn("**重点**", markdown)
        self.assertIn("## 实现", markdown)
        self.assertIn("[来源](https://example.org/source)", markdown)
        self.assertIn("print('ok')", markdown)
        self.assertIn("| 字段 |", markdown)
        self.assertNotIn("Home", markdown)
        self.assertNotIn("window.steal", markdown)
        self.assertNotIn("# 真正标题", markdown)

    def test_full_mode_exposes_nav_as_unselected_recoverable_block(self):
        html = b"<html><body><nav><a href='/home'>Home</a></nav><main><h1>Post</h1><p>A useful paragraph of article content.</p></main><footer>Footer text</footer></body></html>"
        result = convert_html_to_markdown(html, filename="post.htm", mode="full")
        self.assertTrue(any("Home" in block["excerpt"] and not block["recommended"] for block in result["blocks"]))
        self.assertIn("useful paragraph", result["content_markdown"])
        self.assertNotIn("Home", result["content_markdown"])

    def test_active_content_and_unsafe_urls_never_become_targets(self):
        html = b"<html><body><main><h1>Safe</h1><p>Keep this sentence <a href='javascript:alert(1)'>plain</a>.</p><img src='data:image/svg+xml,evil' alt='chart'><script>secret()</script></main></body></html>"
        result = convert_html_to_markdown(html, filename="safe.html")
        self.assertIn("plain", result["content_markdown"])
        self.assertNotIn("javascript:", result["content_markdown"])
        self.assertNotIn("data:image", result["content_markdown"])
        self.assertNotIn("secret()", result["content_markdown"])
        self.assertEqual(result["assets"][0]["original"], "(blocked)")
        self.assertIn("LOCAL_IMAGE_MISSING", [item["code"] for item in result["warnings"]])

    def test_external_image_is_a_link_not_an_auto_loading_image(self):
        html = b"<article><h1>Post</h1><p>Some content in a paragraph.</p><img src='https://example.org/photo.png' alt='Photo'></article>"
        result = convert_html_to_markdown(html, filename="post.html")
        self.assertIn("[", result["content_markdown"])
        self.assertNotIn("![", result["content_markdown"])
        self.assertEqual(result["assets"][0]["status"], "external_link_only")

    def test_binary_empty_and_dynamic_shell_are_rejected(self):
        for data in (b"", b"\x00\x01", b"<html><body><script>render()</script></body></html>"):
            with self.subTest(data=data):
                with self.assertRaises(HtmlImportError):
                    convert_html_to_markdown(data, filename="page.html")


class HtmlImportApiTests(VisitorApiTestCase):
    url = "/api/agent/blog/imports/html/preview/"

    def _post(self, html: bytes, *, name="page.html", **fields):
        file = SimpleUploadedFile(name, html, content_type="text/html")
        return self.client.post(self.url, {"file": file, **fields}, HTTP_HOST="localhost")

    def test_preview_uses_real_jwt_and_does_not_create_article(self):
        article_count = BlogArticle.objects.count()
        response = self._post(b"<article><h1>Import</h1><p>A real article to import.</p></article>")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Import")
        self.assertEqual(response.json()["converter_version"], "html-md-v1")
        self.assertEqual(BlogArticle.objects.count(), article_count)

    def test_anonymous_and_dev_role_header_cannot_preview(self):
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        response = self._post(b"<article><p>Private upload</p></article>")
        self.assertEqual(response.status_code, 401)
        response = self.client.post(
            self.url,
            {"file": SimpleUploadedFile("page.html", b"<p>Private</p>")},
            HTTP_HOST="localhost",
            HTTP_X_ROLE="admin",
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_source_and_large_upload_fail_without_echoing_page(self):
        response = self._post(b"<article><p>SECRET-MARKER</p></article>", source_url="javascript:alert(1)")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("SECRET-MARKER", str(response.json()))
        response = self._post(b"<p>" + b"X" * (5 * 1024 * 1024) + b"</p>")
        self.assertEqual(response.status_code, 413)

    def test_mode_switch_returns_full_selection_without_persistence(self):
        article_count = BlogArticle.objects.count()
        html = b"<html><body><nav>Menu</nav><article><h1>Title</h1><p>Main story content.</p></article></body></html>"
        article = self._post(html, mode="article")
        full = self._post(html, mode="full")
        self.assertEqual(article.status_code, 200)
        self.assertEqual(full.status_code, 200)
        self.assertGreater(len(full.json()["blocks"]), len(article.json()["blocks"]))
        self.assertEqual(BlogArticle.objects.count(), article_count)
