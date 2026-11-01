"""HTML import is a preview-only, authenticated conversion boundary."""

import json
import socket
from io import BytesIO
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from ..models import BlogArticle
from ..services.html_import import HtmlImportError, convert_html_to_markdown
from ..services.remote_blog_image import RemoteImageError, _public_address, _request_pinned, fetch_remote_image
from .support import TEST_MEDIA_ROOT, OperatorApiTestCase, VisitorApiTestCase

TEST_BLOG_IMAGE_STORAGES = {
    **settings.STORAGES,
    "blog_media": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": TEST_MEDIA_ROOT, "base_url": "/media/"},
    },
}


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format="PNG")
    return output.getvalue()


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
        self.assertIn("UNSAFE_IMAGE_SOURCE", [item["code"] for item in result["warnings"]])

    def test_external_image_becomes_renderable_markdown_image(self):
        html = b"<article><h1>Post</h1><p>Some content in a paragraph.</p><img src='https://example.org/photo.png' alt='Photo'></article>"
        result = convert_html_to_markdown(html, filename="post.html")
        self.assertIn("![Photo](https://example.org/photo.png)", result["content_markdown"])
        self.assertEqual(result["assets"][0]["status"], "external_image")
        self.assertIn("EXTERNAL_IMAGE_DEPENDENCY", [item["code"] for item in result["warnings"]])

    def test_saved_page_image_is_mapped_by_placeholder_even_with_source_url(self):
        html = b"<article><h1>Post</h1><p>Some content in a paragraph.</p><img src='./post_files/photo.png' alt='Local'></article>"
        result = convert_html_to_markdown(html, filename="post.html", source_url="https://example.org/post")
        asset = result["assets"][0]
        self.assertEqual(asset["status"], "local_file_required")
        self.assertEqual(asset["original"], "./post_files/photo.png")
        self.assertIn(asset["placeholder"], result["content_markdown"])
        self.assertNotIn("https://example.org/post_files/photo.png", result["content_markdown"])

    def test_lazy_loaded_image_uses_safe_data_src(self):
        html = b"<article><p>A useful image in the article.</p><img src='data:image/gif;base64,a' data-src='https://example.org/real.png' alt='Real'></article>"
        result = convert_html_to_markdown(html, filename="post.html")
        self.assertIn("![Real](https://example.org/real.png)", result["content_markdown"])

    def test_file_image_needs_local_upload_without_exposing_machine_path(self):
        html = b"<article><p>Saved webpage with a local image.</p><img src='file:///C:/Users/Alice/Pictures/chart.png' alt='Chart'></article>"
        result = convert_html_to_markdown(html, filename="post.html")
        self.assertEqual(result["assets"][0]["original"], "chart.png")
        self.assertIn(result["assets"][0]["placeholder"], result["content_markdown"])
        self.assertNotIn("Alice", str(result))

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
        self.assertEqual(response.json()["converter_version"], "html-md-v2")
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


class RemoteImageServiceTests(TestCase):
    def test_blocks_private_dns_and_literal_addresses(self):
        with self.assertRaises(RemoteImageError):
            fetch_remote_image("http://127.0.0.1/secret.png")
        addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.5", 443)),
        ]
        with patch("apps.agent_api.services.remote_blog_image.socket.getaddrinfo", return_value=addresses):
            with self.assertRaises(RemoteImageError):
                _public_address("cdn.example.org", 443)

    def test_connection_uses_checked_ip_with_original_tls_hostname(self):
        with patch("apps.agent_api.services.remote_blog_image.http.client.HTTPSConnection") as connection_type:
            with patch("apps.agent_api.services.remote_blog_image.socket.create_connection") as create_socket:
                connection = _request_pinned("cdn.example.org", 443, "93.184.216.34", secure=True, path="/a.png")
                connection._create_connection(("cdn.example.org", 443), timeout=5)
        self.assertEqual(connection, connection_type.return_value)
        self.assertEqual(connection_type.call_args.args[:2], ("cdn.example.org", 443))
        create_socket.assert_called_once_with(("93.184.216.34", 443), timeout=5)

    def test_fetch_validates_bytes_and_rejects_redirects(self):
        response = Mock()
        response.status = 200
        response.getheader.side_effect = lambda name, default="": {
            "Content-Type": "image/png",
            "Content-Length": str(len(png_bytes())),
        }.get(name, default)
        response.read.return_value = png_bytes()
        connection = Mock()
        connection.getresponse.return_value = response
        with patch("apps.agent_api.services.remote_blog_image._public_address", return_value="93.184.216.34"):
            with patch("apps.agent_api.services.remote_blog_image._request_pinned", return_value=connection):
                data, suffix = fetch_remote_image("https://cdn.example.org/a.png")
                self.assertEqual(data, png_bytes())
                self.assertEqual(suffix, ".png")
                response.status = 302
                with self.assertRaises(RemoteImageError):
                    fetch_remote_image("https://cdn.example.org/redirect")

    def test_rejects_type_mismatch_and_nonstandard_port(self):
        with self.assertRaises(RemoteImageError):
            fetch_remote_image("https://cdn.example.org:8080/photo.png")
        response = Mock(status=200)
        response.getheader.side_effect = lambda name, default="": {
            "Content-Type": "image/jpeg",
            "Content-Length": str(len(png_bytes())),
        }.get(name, default)
        response.read.return_value = png_bytes()
        connection = Mock()
        connection.getresponse.return_value = response
        with patch("apps.agent_api.services.remote_blog_image._public_address", return_value="93.184.216.34"):
            with patch("apps.agent_api.services.remote_blog_image._request_pinned", return_value=connection):
                with self.assertRaises(RemoteImageError):
                    fetch_remote_image("https://cdn.example.org/a.png")

    def test_closed_connection_socket_still_reads_complete_response(self):
        response = Mock(status=200)
        response.getheader.side_effect = lambda name, default="": {
            "Content-Type": "image/png",
            "Content-Length": str(len(png_bytes())),
        }.get(name, default)
        response.read.return_value = png_bytes()
        connection = Mock(sock=None)
        connection.getresponse.return_value = response
        with patch("apps.agent_api.services.remote_blog_image._public_address", return_value="93.184.216.34"):
            with patch("apps.agent_api.services.remote_blog_image._request_pinned", return_value=connection):
                self.assertEqual(fetch_remote_image("https://cdn.example.org/a.png"), (png_bytes(), ".png"))

    def test_rejects_truncated_response(self):
        response = Mock(status=200)
        response.getheader.side_effect = lambda name, default="": {
            "Content-Type": "image/png",
            "Content-Length": str(len(png_bytes()) + 1),
        }.get(name, default)
        response.read.side_effect = [png_bytes(), b""]
        connection = Mock(sock=None)
        connection.getresponse.return_value = response
        with patch("apps.agent_api.services.remote_blog_image._public_address", return_value="93.184.216.34"):
            with patch("apps.agent_api.services.remote_blog_image._request_pinned", return_value=connection):
                with self.assertRaisesRegex(RemoteImageError, "下载不完整"):
                    fetch_remote_image("https://cdn.example.org/a.png")


class HtmlImportImageApiTests(OperatorApiTestCase):
    url = "/api/agent/blog/imports/html/images/fetch/"

    @override_settings(STORAGES=TEST_BLOG_IMAGE_STORAGES)
    @patch("apps.agent_api.views.blog_imports.fetch_remote_image")
    def test_download_is_stored_and_readable_from_site(self, fetch):
        fetch.return_value = (png_bytes(), ".png")
        response = self.client.post(
            self.url,
            json.dumps({"url": "https://cdn.example.org/a.png"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 201)
        image_url = response.json()["url"]
        self.assertRegex(image_url, r"^/media/blog/[0-9a-f]{32}\.png$")
        readback = self.client.get(image_url, HTTP_HOST="localhost")
        self.assertEqual(readback.status_code, 200)
        self.assertEqual(b"".join(readback.streaming_content), png_bytes())

    @patch("apps.agent_api.views.blog_imports.fetch_remote_image")
    def test_upstream_failure_does_not_store_or_claim_success(self, fetch):
        fetch.side_effect = RemoteImageError("图片下载失败，请选择本地图片文件")
        response = self.client.post(
            self.url,
            json.dumps({"url": "https://cdn.example.org/missing.png"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("本地图片", response.json()["detail"])

    def test_anonymous_and_visitor_cannot_trigger_server_fetch(self):
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        response = self.client.post(
            self.url,
            json.dumps({"url": "https://cdn.example.org/a.png"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 401)
        self.authenticate_test_user("visitor")
        response = self.client.post(
            self.url,
            json.dumps({"url": "https://cdn.example.org/a.png"}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 403)

    def test_non_object_payload_is_rejected_without_fetch(self):
        with patch("apps.agent_api.views.blog_imports.fetch_remote_image") as fetch:
            response = self.client.post(
                self.url,
                json.dumps(["https://cdn.example.org/a.png"]),
                content_type="application/json",
                HTTP_HOST="localhost",
            )
        self.assertEqual(response.status_code, 400)
        fetch.assert_not_called()
