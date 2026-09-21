from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse, JsonResponse
from django.urls import include, path
from django.urls import re_path
from django.views.static import serve as serve_static


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


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/agent/", include("apps.agent_api.urls")),
    path("api/", include("apps.core.urls")),
    # The Docker frontend serves this path directly. Django keeps a local
    # fallback so `start.bat`/`start.sh` only need one application server.
    re_path(
        r"^assets/(?P<path>.*)$",
        serve_static,
        {"document_root": settings.FRONTEND_DIST / "assets"},
    ),
    # Vue Router uses history mode, so every non-backend route must return the
    # same SPA entry point (for example /blog/slug or /knowledge).
    re_path(
        r"^(?!api/|admin/|assets/|static/|media/).*$",
        spa_index,
        name="spa",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
