"""Request-time HTML for one published article; the Vue app still owns interaction."""

import re
from html import escape
from urllib.parse import quote, urlsplit
from xml.sax.saxutils import escape as xml_escape

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.html import strip_tags

from agent.security import DEFAULT_WORKSPACE_KEY
from apps.agent_api.models import BlogArticle
from apps.agent_api.services.blog_media import is_blog_image_name


def _plain_excerpt(value: str, limit: int = 240) -> str:
    plain = " ".join(strip_tags(value or "").split())
    return plain[: limit - 1].rstrip() + "…" if len(plain) > limit else plain


def _public_cover(request, value: str) -> str:
    """Only expose an absolute, publicly reachable image URL in share metadata."""
    value = (value or "").strip()
    if value.startswith("/media/blog/") and is_blog_image_name(value.removeprefix("/media/blog/")):
        return request.build_absolute_uri(value)
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
        return value
    return ""


def public_article_page(request, slug: str):
    index_path = settings.FRONTEND_DIST / "index.html"
    if not index_path.is_file():
        return JsonResponse(
            {
                "detail": "Frontend build not found.",
                "action": "Run `npm --prefix frontend run build` or use start.bat/start.sh.",
            },
            status=503,
        )

    html = index_path.read_text(encoding="utf-8")
    article = (
        BlogArticle.objects.filter(
            slug=slug,
            workspace_key=DEFAULT_WORKSPACE_KEY,
            status=BlogArticle.Status.PUBLISHED,
        )
        .only("title", "summary", "cover_image", "published_at", "updated_at")
        .first()
    )

    if article is None:
        # Keep the SPA shell so a signed-in author can still open a private draft.
        # A public crawler receives neither the private text nor an indexable page.
        response = HttpResponse(html, content_type="text/html; charset=utf-8", status=404)
        response["X-Robots-Tag"] = "noindex, nofollow"
    else:
        title = escape(article.title)
        description = escape(_plain_excerpt(article.summary or article.content))
        canonical = escape(request.build_absolute_uri(f"/blog/{quote(slug, safe='')}/"), quote=True)
        cover = _public_cover(request, article.cover_image)
        head = [
            f"<title>{title}</title>",
            f'<meta data-blog-seo name="description" content="{description}">',
            f'<link data-blog-seo rel="canonical" href="{canonical}">',
            '<meta data-blog-seo property="og:type" content="article">',
            f'<meta data-blog-seo property="og:title" content="{escape(article.title, quote=True)}">',
            f'<meta data-blog-seo property="og:description" content="{description}">',
            f'<meta data-blog-seo property="og:url" content="{canonical}">',
            f'<meta data-blog-seo name="twitter:card" content="{"summary_large_image" if cover else "summary"}">',
            f'<meta data-blog-seo name="twitter:title" content="{escape(article.title, quote=True)}">',
            f'<meta data-blog-seo name="twitter:description" content="{description}">',
        ]
        if cover:
            head.extend(
                (
                    f'<meta data-blog-seo property="og:image" content="{escape(cover, quote=True)}">',
                    f'<meta data-blog-seo name="twitter:image" content="{escape(cover, quote=True)}">',
                )
            )
        if article.published_at:
            head.append(
                f'<meta data-blog-seo property="article:published_time" content="{article.published_at.isoformat()}">'
            )
        head.append(f'<meta data-blog-seo property="article:modified_time" content="{article.updated_at.isoformat()}">')
        html = re.sub(r"<title>.*?</title>", "", html, count=1, flags=re.DOTALL | re.IGNORECASE)
        html = html.replace("</head>", "\n    " + "\n    ".join(head) + "\n  </head>", 1)
        preview = (
            '<main style="max-width:760px;margin:6rem auto;padding:0 1.5rem;font:16px/1.7 sans-serif">'
            f"<article><h1>{title}</h1><p>{description}</p></article></main>"
        )
        html = html.replace('<div id="app"></div>', f'<div id="app">{preview}</div>', 1)
        response = HttpResponse(html, content_type="text/html; charset=utf-8")

    # Publication edits and withdrawals must not leave stale share cards at a cache.
    response["Cache-Control"] = "no-store"
    return response


def public_sitemap(request):
    urls = []
    articles = (
        BlogArticle.objects.filter(
            workspace_key=DEFAULT_WORKSPACE_KEY,
            status=BlogArticle.Status.PUBLISHED,
        )
        .order_by("id")
        .values_list("slug", "updated_at")
    )
    for slug, updated_at in articles.iterator():
        location = request.build_absolute_uri(f"/blog/{quote(slug, safe='')}/")
        urls.append(f"<url><loc>{xml_escape(location)}</loc><lastmod>{updated_at.date().isoformat()}</lastmod></url>")
    body = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    body += "".join(urls) + "</urlset>"
    response = HttpResponse(body, content_type="application/xml; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


def public_robots(request):
    sitemap = request.build_absolute_uri("/sitemap.xml")
    response = HttpResponse(f"User-agent: *\nAllow: /\nSitemap: {sitemap}\n", content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response
