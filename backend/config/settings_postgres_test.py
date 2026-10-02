"""Fail-closed settings for the isolated PostgreSQL/pgvector integration suite."""

import os
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

if os.environ.get("BLOG_PGVECTOR_INTEGRATION") != "1":
    raise ImproperlyConfigured("Set BLOG_PGVECTOR_INTEGRATION=1 to enable the isolated PostgreSQL test profile.")

database_url = os.environ.get("DATABASE_URL", "")
parsed_database_url = urlparse(database_url)
if parsed_database_url.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
    raise ImproperlyConfigured("PostgreSQL integration tests require a PostgreSQL DATABASE_URL.")
if parsed_database_url.path.lstrip("/") != "blog_pgvector_ci":
    raise ImproperlyConfigured("PostgreSQL integration tests are restricted to the blog_pgvector_ci database.")
if parsed_database_url.hostname not in {"localhost", "127.0.0.1", "postgres"}:
    raise ImproperlyConfigured("PostgreSQL integration tests may only use a local or CI service hostname.")

os.environ.setdefault("DJANGO_SECRET_KEY", "isolated-pgvector-test-key-not-production-0123456789")
os.environ["BLOG_LOCAL_MODE"] = "false"
os.environ["DJANGO_DEBUG"] = "false"
os.environ["AGENT_SECURITY_ENFORCED"] = "true"
os.environ["DJANGO_HTTPS_TERMINATED"] = "true"
os.environ["DJANGO_SECURE_SSL_REDIRECT"] = "true"
os.environ["BLOG_MEDIA_STORAGE"] = "file"
os.environ["RAG_VECTOR_BACKEND"] = "pgvector"
os.environ["AGENT_FORCE_LOCAL_EMBEDDINGS"] = "true"
os.environ["RAG_EMBEDDING_MODE"] = "local_hash"
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")

from . import settings as base_settings  # noqa: E402

for setting_name in dir(base_settings):
    if setting_name.isupper():
        globals()[setting_name] = getattr(base_settings, setting_name)

database_config = globals()["DATABASES"]
if database_config["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("The pgvector integration profile resolved to a non-PostgreSQL database.")

database_config["default"].setdefault("TEST", {})["NAME"] = "test_blog_pgvector_ci"
