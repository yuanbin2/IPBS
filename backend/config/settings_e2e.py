"""Isolated settings for the browser upload smoke suite.

The E2E runner supplies a unique temporary data root for every run. This keeps
the real developer database, media directory, and configured Bucket untouched.
"""

import os
from pathlib import Path

os.environ.setdefault("RAG_EMBEDDING_MODE", "local_hash")

from .settings import *  # noqa: F403

E2E_TEST_MODE = True
E2E_DATA_ROOT = Path(os.environ["E2E_DATA_ROOT"]).resolve()
DEBUG = True
_frontend_port = os.getenv("E2E_FRONTEND_PORT", "5173")
CSRF_TRUSTED_ORIGINS = [  # noqa: F405
    *CSRF_TRUSTED_ORIGINS,  # noqa: F405
    f"http://127.0.0.1:{_frontend_port}",
    f"http://localhost:{_frontend_port}",
]
MIDDLEWARE = ["config.e2e_middleware.UploadContractObservationMiddleware", *MIDDLEWARE]  # noqa: F405
DATABASES = {  # noqa: F405
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": E2E_DATA_ROOT / "db.sqlite3",
    }
}
MEDIA_ROOT = E2E_DATA_ROOT / "media"
STORAGES = {  # noqa: F405
    **STORAGES,  # noqa: F405
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": MEDIA_ROOT, "base_url": MEDIA_URL},  # noqa: F405
    },
    "blog_media": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": MEDIA_ROOT, "base_url": MEDIA_URL},  # noqa: F405
    },
}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
