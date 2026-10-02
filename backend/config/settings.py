import os
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv(PROJECT_ROOT / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


LOCAL_MODE = env_bool("BLOG_LOCAL_MODE")
_LOCAL_SECRET_KEY = "dev-only-change-me-use-at-least-32-bytes"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", _LOCAL_SECRET_KEY if LOCAL_MODE else "").strip()
if LOCAL_MODE and len(SECRET_KEY) < 32:
    SECRET_KEY = _LOCAL_SECRET_KEY
if not LOCAL_MODE and (len(SECRET_KEY) < 50 or SECRET_KEY.lower().startswith("change-me")):
    raise RuntimeError("Set DJANGO_SECRET_KEY to a private value with at least 50 characters outside local mode.")
DEBUG = LOCAL_MODE or env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")]
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
if RAILWAY_PUBLIC_DOMAIN and RAILWAY_PUBLIC_DOMAIN not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)
RAILWAY_ENVIRONMENT_NAME = os.getenv("RAILWAY_ENVIRONMENT_NAME", "").strip()
AGENT_SECURITY_ENFORCED = env_bool("AGENT_SECURITY_ENFORCED", not LOCAL_MODE)
if not LOCAL_MODE and DEBUG:
    raise RuntimeError("DJANGO_DEBUG must be false outside local mode.")
if not LOCAL_MODE and not AGENT_SECURITY_ENFORCED:
    raise RuntimeError("AGENT_SECURITY_ENFORCED must be true outside local mode.")
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
DJANGO_HTTPS_TERMINATED = env_bool("DJANGO_HTTPS_TERMINATED", bool(RAILWAY_ENVIRONMENT_NAME))
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", DJANGO_HTTPS_TERMINATED)
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "3600" if DJANGO_HTTPS_TERMINATED else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", DJANGO_HTTPS_TERMINATED)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", DJANGO_HTTPS_TERMINATED)
if not LOCAL_MODE:
    if not DJANGO_HTTPS_TERMINATED:
        raise RuntimeError("Set DJANGO_HTTPS_TERMINATED=true behind a verified TLS-terminating proxy.")
    if not SECURE_SSL_REDIRECT:
        raise RuntimeError("DJANGO_SECURE_SSL_REDIRECT must be true outside local mode.")
    if SECURE_HSTS_SECONDS < 1:
        raise RuntimeError("DJANGO_SECURE_HSTS_SECONDS must be greater than zero outside local mode.")
    if not SESSION_COOKIE_SECURE or not CSRF_COOKIE_SECURE:
        raise RuntimeError("Session and CSRF cookies must be Secure outside local mode.")
# Railway terminates public TLS before forwarding traffic. Keep HSTS staged at
# one hour and scoped to the exact host; don't opt into subdomain HSTS or preload
# until every subdomain and the production domain have been audited. Django's
# corresponding advisories are intentionally silenced for this deployment profile.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"] if DJANGO_HTTPS_TERMINATED else []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "apps.agent_api",
    "apps.core",
    "apps.users",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [PROJECT_ROOT / "frontend" / "dist"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

default_database_url = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
if LOCAL_MODE:
    # A one-command local run must not depend on PostgreSQL settings left in
    # .env by a previous Docker deployment.
    DATABASES = {"default": dj_database_url.parse(default_database_url)}
else:
    DATABASES = {
        "default": dj_database_url.config(default=default_database_url, conn_max_age=600),
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
USE_I18N = True
USE_TZ = True

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


def _blog_media_storage_settings():
    """Configure public blog images independently from other uploaded files."""
    storage_mode = os.getenv("BLOG_MEDIA_STORAGE", "file" if LOCAL_MODE else "s3").strip().lower()
    if storage_mode == "file":
        return {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": MEDIA_ROOT, "base_url": MEDIA_URL},
        }
    if storage_mode != "s3":
        raise RuntimeError("BLOG_MEDIA_STORAGE must be either 'file' or 's3'.")

    required = {
        "BLOG_MEDIA_BUCKET_NAME": os.getenv("BLOG_MEDIA_BUCKET_NAME", "").strip(),
        "BLOG_MEDIA_ENDPOINT": os.getenv("BLOG_MEDIA_ENDPOINT", "").strip(),
        "BLOG_MEDIA_REGION": os.getenv("BLOG_MEDIA_REGION", "").strip(),
        "BLOG_MEDIA_ACCESS_KEY_ID": os.getenv("BLOG_MEDIA_ACCESS_KEY_ID", "").strip(),
        "BLOG_MEDIA_SECRET_ACCESS_KEY": os.getenv("BLOG_MEDIA_SECRET_ACCESS_KEY", "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError("BLOG_MEDIA_STORAGE=s3 requires: " + ", ".join(missing))

    return {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": required["BLOG_MEDIA_BUCKET_NAME"],
            "endpoint_url": required["BLOG_MEDIA_ENDPOINT"],
            "region_name": required["BLOG_MEDIA_REGION"],
            "access_key": required["BLOG_MEDIA_ACCESS_KEY_ID"],
            "secret_key": required["BLOG_MEDIA_SECRET_ACCESS_KEY"],
            "addressing_style": "virtual",
            "signature_version": "s3v4",
            "default_acl": None,
            "querystring_auth": True,
            "file_overwrite": False,
            "location": "",
            "object_parameters": {"CacheControl": "public, max-age=31536000, immutable"},
        },
    }


# Blog uploads contain public article images only. Keep other uploaded files on
# the default private/local storage until they have an explicit access policy.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "blog_media": _blog_media_storage_settings(),
}

_default_cors_origins = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CORS_ALLOWED_ORIGINS", _default_cors_origins).split(",")
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS = True
if LOCAL_MODE:
    CSRF_TRUSTED_ORIGINS += [origin for origin in CORS_ALLOWED_ORIGINS if origin not in CSRF_TRUSTED_ORIGINS]

JWT_REFRESH_COOKIE_NAME = "blog_refresh"
JWT_REFRESH_COOKIE_PATH = "/api/agent/auth/cookie/"
JWT_REFRESH_COOKIE_SAMESITE = "Lax"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "EXCEPTION_HANDLER": "apps.agent_api.exceptions.exception_handler",
}

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
CELERY_BROKER_URL = RABBITMQ_URL
CELERY_RESULT_BACKEND = "cache+memory://" if LOCAL_MODE else REDIS_URL
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_RESULT_EXPIRES = 60 * 60 * 24
CELERY_TASK_ALWAYS_EAGER = LOCAL_MODE or "test" in sys.argv or env_bool("CELERY_TASK_ALWAYS_EAGER")
CELERY_TASK_EAGER_PROPAGATES = "test" in sys.argv or env_bool("CELERY_TASK_EAGER_PROPAGATES")
CELERY_TASK_ROUTES = {
    "apps.agent_api.tasks.ingest_document_task": {"queue": "documents"},
    "apps.agent_api.tasks.run_evaluation_batch_task": {"queue": "evaluations"},
}
CELERY_BEAT_SCHEDULE = {
    "dispatch-document-ingestion-outbox": {
        "task": "apps.agent_api.tasks.dispatch_document_ingestion_outbox",
        "schedule": 30.0,
        "options": {"queue": "documents"},
    },
}

if LOCAL_MODE or os.getenv("CACHE_BACKEND", "").strip().lower() == "locmem":
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "knowledge-agent-local",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.getenv("REDIS_CACHE_URL", "redis://localhost:6379/1"),
        }
    }

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_ACCESS_MINUTES", "15"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("JWT_REFRESH_DAYS", "7"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "SIGNING_KEY": SECRET_KEY,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
# Force redeploy Tue Sep 22 02:12:12     2026
