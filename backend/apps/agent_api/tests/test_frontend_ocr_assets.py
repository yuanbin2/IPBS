"""The local single-port SPA must serve OCR assets instead of index.html."""

import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings


class FrontendOcrAssetRoutingTests(SimpleTestCase):
    def test_manifest_and_runtime_are_static_files_not_spa_html(self):
        with tempfile.TemporaryDirectory() as temporary:
            dist = Path(temporary)
            (dist / "index.html").write_text("<!doctype html><title>SPA</title>", encoding="utf-8")
            models = dist / "models" / "ocr"
            models.mkdir(parents=True)
            manifest = {"files": {"models/ocr/model.ort": {"bytes": 3, "sha256": "abc"}}}
            (models / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (models / "model.ort").write_bytes(b"ort")
            runtime = dist / "ort"
            runtime.mkdir()
            (runtime / "ort-wasm-simd-threaded.wasm").write_bytes(b"wasm")

            with override_settings(FRONTEND_DIST=dist):
                response = self.client.get("/models/ocr/manifest.json")
                self.assertEqual(response.status_code, 200)
                self.assertIn("application/json", response["Content-Type"])
                self.assertEqual(json.loads(b"".join(response.streaming_content)), manifest)

                response = self.client.get("/models/ocr/model.ort")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"ort")

                response = self.client.get("/ort/ort-wasm-simd-threaded.wasm")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"wasm")

                self.assertEqual(self.client.get("/models/ocr/missing.json").status_code, 404)
                self.assertEqual(self.client.get("/ort/missing.wasm").status_code, 404)

                response = self.client.get("/blog")
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"<!doctype html>", b"".join(response.streaming_content))
