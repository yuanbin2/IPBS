"""The local single-port SPA must serve editor typesetting assets, not index.html."""

import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings


class FrontendEditorAssetRoutingTests(SimpleTestCase):
    def test_vendor_assets_are_static_files_not_spa_html(self):
        """Vditor 的 lute/katex 等运行时资源走 /vendor/；缺失必须 404 而非 SPA 兜底。"""
        with tempfile.TemporaryDirectory() as temporary:
            dist = Path(temporary)
            (dist / "index.html").write_text("<!doctype html><title>SPA</title>", encoding="utf-8")
            lute = dist / "vendor" / "vditor" / "dist" / "js" / "lute"
            lute.mkdir(parents=True)
            (lute / "lute.min.js").write_bytes(b"window.Lute={};")

            with override_settings(FRONTEND_DIST=dist):
                response = self.client.get("/vendor/vditor/dist/js/lute/lute.min.js")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"window.Lute={};")

                self.assertEqual(
                    self.client.get("/vendor/vditor/dist/js/lute/missing.js").status_code,
                    404,
                )
                # SPA 兜底继续生效，但不得吞掉 /vendor/ 路径。
                response = self.client.get("/blog")
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"<!doctype html>", b"".join(response.streaming_content))
