from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import FileResponse, HttpResponseNotFound, JsonResponse
from django.urls import include, path, re_path
from django.views.static import serve as serve_static

from apps.agent_api.views.blog_articles import BlogImageReadView
from config.public_article_page import public_article_page, public_robots, public_sitemap


def spa_index(request):
    """Serve the built SPA or return an actionable response instead of a 500."""
    index_path = settings.FRONTEND_DIST / "index.html"
    if not index_path.is_file():
        return JsonResponse(
            {
                "detail": "Frontend build not found.",
                "action": "Run `npm --prefix frontend run build` or use start.bat/start.sh.",
            },
            status=503,
        )
    return FileResponse(index_path.open("rb"), content_type="text/html")


def deny_legacy_private_media(request):
    return HttpResponseNotFound()


def serve_frontend_static(request, path, subdir):
    """Resolve the build directory at request time for local runs and tests."""
    return serve_static(request, path, document_root=settings.FRONTEND_DIST / subdir)


urlpatterns = [
    path("admin/", admin.site.urls),
    # 旧版本可能曾将私有笔记图片放在公开 MEDIA_ROOT/private-notes。
    # 即使尚未运行搬迁命令，也不能让 DEBUG static() 直接读取它们。
    re_path(r"(?i)^media/private-notes(?:/|$).*$", deny_legacy_private_media),
    # Stable legacy /media/blog/... URLs now pass through a strict public-image
    # allowlist and the configured private storage backend in every environment.
    re_path(
        r"^media/blog/(?P<filename>[^/]+)$",
        BlogImageReadView.as_view(),
        name="blog-image-read",
    ),
    path("api/agent/", include("apps.agent_api.urls")),
    path("api/", include("apps.core.urls")),
    # The Docker frontend serves this path directly. Django keeps a local
    # fallback so `start.bat`/`start.sh` only need one application server.
    re_path(
        r"^assets/(?P<path>.*)$",
        serve_frontend_static,
        {"subdir": "assets"},
    ),
    # The local single-port launcher serves Vite's public OCR model and ORT
    # runtime files from dist. Without these routes the SPA fallback returns
    # index.html for manifest.json, which breaks JSON parsing in the OCR worker.
    re_path(
        r"^models/ocr/(?P<path>.*)$",
        serve_frontend_static,
        {"subdir": "models/ocr"},
    ),
    re_path(
        r"^ort/(?P<path>.*)$",
        serve_frontend_static,
        {"subdir": "ort"},
    ),
    # Vditor 编辑器与 md-editor-v3 阅读页的公式/流程图/代码高亮资源
    # （scripts/sync-editor-assets.mjs 生成）。缺少该路由时 SPA 兜底会把
    # lute/katex 等 JS 返回成 HTML，编辑器初始化直接失败。
    re_path(
        r"^vendor/(?P<path>.*)$",
        serve_frontend_static,
        {"subdir": "vendor"},
    ),
    path("robots.txt", public_robots),
    path("sitemap.xml", public_sitemap),
    # Only single-segment article URLs receive request-time public metadata.
    # The collection and settings routes keep their existing SPA behavior.
    re_path(r"^blog/(?!(?:collections|settings)(?:/|$))(?P<slug>[^/]+)/?$", public_article_page),
    # Vue Router uses history mode, so every non-backend route must return the
    # same SPA entry point (for example /blog/slug or /knowledge).
    re_path(
        r"^(?!api/|admin/|assets/|models/ocr/|ort/|vendor/|static/|media/).*$",
        spa_index,
        name="spa",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
