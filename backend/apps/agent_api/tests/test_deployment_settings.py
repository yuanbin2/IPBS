"""Production settings fail closed without reading a developer's .env file."""

import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

BACKEND_ROOT = Path(__file__).resolve().parents[3]
LOAD_SETTINGS = (
    "import dotenv; dotenv.load_dotenv = lambda *args, **kwargs: False; " "import config.settings; print('settings-ok')"
)
CHECK_DEPLOY = (
    "import dotenv; dotenv.load_dotenv = lambda *args, **kwargs: False; "
    "from django.core.management import execute_from_command_line; "
    "execute_from_command_line(['manage.py', 'check', '--deploy'])"
)


class DeploymentSettingsTests(TestCase):
    def _settings_process(self, *, check_deploy=False, **changes):
        environment = {
            key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ
        }
        environment.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "BLOG_LOCAL_MODE": "false",
                "DJANGO_SECRET_KEY": "isolated-settings-test-key-not-for-deployment-0123456789abcdefghijkl",
                "DJANGO_ALLOWED_HOSTS": "blog.example.test",
                "DJANGO_HTTPS_TERMINATED": "true",
                "DJANGO_DEBUG": "false",
                "AGENT_SECURITY_ENFORCED": "true",
                "BLOG_MEDIA_STORAGE": "file",
                "DATABASE_URL": "postgres://test_user:isolated-private-value@127.0.0.1:5432/isolated_settings",
                "REDIS_URL": "redis://127.0.0.1:6379/0",
                "REDIS_CACHE_URL": "redis://127.0.0.1:6379/1",
                "RABBITMQ_URL": "amqp://test_user:isolated-private-value@127.0.0.1:5672/isolated_settings",
            }
        )
        for key, value in changes.items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        return subprocess.run(
            [sys.executable, "-c", CHECK_DEPLOY if check_deploy else LOAD_SETTINGS],
            cwd=BACKEND_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_complete_isolated_production_settings_load(self):
        result = self._settings_process()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("settings-ok", result.stdout)

    def test_local_mode_still_loads_without_production_services(self):
        result = self._settings_process(
            BLOG_LOCAL_MODE="true",
            DJANGO_SECRET_KEY=None,
            DJANGO_ALLOWED_HOSTS=None,
            DJANGO_HTTPS_TERMINATED=None,
            DATABASE_URL=None,
            REDIS_URL=None,
            REDIS_CACHE_URL=None,
            RABBITMQ_URL=None,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("settings-ok", result.stdout)

    def test_isolated_production_check_deploy(self):
        result = self._settings_process(check_deploy=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("System check identified no issues", result.stdout + result.stderr)

    def test_missing_or_unsafe_production_settings_fail_closed(self):
        cases = (
            ({"DJANGO_SECRET_KEY": None}, "DJANGO_SECRET_KEY"),
            ({"DJANGO_ALLOWED_HOSTS": None}, "DJANGO_ALLOWED_HOSTS"),
            ({"DJANGO_ALLOWED_HOSTS": "*"}, "DJANGO_ALLOWED_HOSTS"),
            ({"DJANGO_ALLOWED_HOSTS": ".example.test"}, "DJANGO_ALLOWED_HOSTS"),
            ({"DJANGO_DEBUG": "true"}, "DJANGO_DEBUG"),
            ({"AGENT_SECURITY_ENFORCED": "false"}, "AGENT_SECURITY_ENFORCED"),
            ({"DJANGO_HTTPS_TERMINATED": None}, "DJANGO_HTTPS_TERMINATED"),
            ({"DJANGO_SECURE_SSL_REDIRECT": "false"}, "DJANGO_SECURE_SSL_REDIRECT"),
            ({"DJANGO_SESSION_COOKIE_SECURE": "false"}, "cookies must be Secure"),
            ({"DJANGO_CSRF_TRUSTED_ORIGINS": "http://blog.example.test"}, "exact HTTPS origins"),
            ({"DJANGO_CORS_ALLOWED_ORIGINS": "http://localhost:5173"}, "exact HTTPS origins"),
            ({"DATABASE_URL": None}, "DATABASE_URL"),
            ({"DATABASE_URL": "postgres://postgres:postgres@localhost:5432/blog"}, "example password"),
            ({"DATABASE_URL": "postgres://postgres:%70ostgres@localhost:5432/blog"}, "example password"),
            ({"REDIS_URL": None}, "REDIS_URL"),
            ({"REDIS_CACHE_URL": None}, "REDIS_CACHE_URL"),
            ({"RABBITMQ_URL": None}, "RABBITMQ_URL"),
            ({"RABBITMQ_URL": "amqp://blog:blog@localhost:5672/blog"}, "example password"),
            ({"CACHE_BACKEND": "locmem"}, "LocMem cache"),
            ({"CELERY_TASK_ALWAYS_EAGER": "true"}, "eager Celery"),
        )
        for changes, expected in cases:
            with self.subTest(changes=changes):
                result = self._settings_process(**changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("isolated-private-value", result.stderr)
