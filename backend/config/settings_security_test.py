"""Production security profile with an isolated SQLite database and media root."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault(
    "DJANGO_SECRET_KEY",
    "ci-only-blog-security-test-key-2026-not-a-production-secret-1234567890",
)
os.environ["DJANGO_DEBUG"] = "false"
os.environ["AGENT_SECURITY_ENFORCED"] = "true"
os.environ["DJANGO_HTTPS_TERMINATED"] = "true"
os.environ["DJANGO_SECURE_SSL_REDIRECT"] = "true"
os.environ["BLOG_MEDIA_STORAGE"] = "file"
os.environ["RAG_EMBEDDING_MODE"] = "local_hash"
os.environ["DJANGO_ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"


def _load_base_settings():
    from . import settings

    return settings


base_settings = _load_base_settings()

for _setting_name in dir(base_settings):
    if _setting_name.isupper():
        globals()[_setting_name] = getattr(base_settings, _setting_name)


_TEST_DATA = tempfile.TemporaryDirectory(prefix="blog-security-tests-")
_TEST_DATA_ROOT = Path(_TEST_DATA.name)

DEBUG = False
AGENT_SECURITY_ENFORCED = True
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _TEST_DATA_ROOT / "security-tests.sqlite3",
    }
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "blog-isolated-security-tests",
    }
}
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
MEDIA_ROOT = _TEST_DATA_ROOT / "media"
STORAGES = {
    **base_settings.STORAGES,
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": MEDIA_ROOT},
    },
    "blog_media": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": MEDIA_ROOT / "blog", "base_url": "/media/"},
    },
}
