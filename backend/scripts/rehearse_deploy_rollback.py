"""Run an isolated local release, inject a failed migration, and roll back.

This exercises real HTTP processes and a disposable SQLite database. It does
not claim to validate Docker, PostgreSQL, a TLS proxy, or production images.
Run with the repository root .venv Python; no existing database is opened.
"""

import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[2]
PYTHON = sys.executable
QUERY = "i019 violet atlas checkpoint"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def environment(data_root):
    return dict(
        os.environ,
        PYTHON_DOTENV_DISABLED="1",
        DJANGO_SETTINGS_MODULE="config.settings_e2e",
        BLOG_LOCAL_MODE="true",
        AGENT_SECURITY_ENFORCED="true",
        E2E_DATA_ROOT=str(data_root),
        RAG_EMBEDDING_MODE="local_hash",
        RAG_VECTOR_BACKEND="sqlite",
        BLOG_MEDIA_STORAGE="file",
        LANGCHAIN_TRACING_V2="false",
        LANGSMITH_TRACING="false",
    )


def build_frontend(destination):
    frontend = REPO / "frontend"
    require((frontend / "node_modules" / "vite" / "bin" / "vite.js").is_file(), "Local frontend dependencies missing")
    for arguments in (
        ["node", "node_modules/vue-tsc/bin/vue-tsc.js", "--noEmit"],
        ["node", "node_modules/vite/bin/vite.js", "build", "--outDir", str(destination)],
    ):
        result = subprocess.run(
            arguments, cwd=frontend, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180
        )
        if result.returncode:
            raise RuntimeError(f"Frontend verification failed: {arguments[1]}: {result.stderr[-500:]}")
    require((destination / "index.html").is_file(), "Frontend build did not produce index.html")


def copy_release(destination, frontend_dist):
    backend = destination / "backend"
    backend.mkdir(parents=True)
    for name in ("agent", "apps", "config"):
        shutil.copytree(
            REPO / "backend" / name,
            backend / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    for name in ("manage.py", "requirements.txt"):
        shutil.copy2(REPO / "backend" / name, backend / name)
    shutil.copytree(frontend_dist, destination / "frontend" / "dist")


def release_hash(release):
    digest = hashlib.sha256()
    for path in sorted(release.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(release).as_posix().encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run_manage(release, data_root, *arguments, must_succeed=True):
    result = subprocess.run(
        [PYTHON, str(release / "backend" / "manage.py"), *arguments],
        cwd=release / "backend",
        env=environment(data_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    if must_succeed and result.returncode:
        raise RuntimeError(f"manage.py {arguments[0]} failed: {result.stderr[-500:]}")
    return result


def child_seed(release, data_root):
    os.environ.update(environment(data_root))
    sys.path.insert(0, str(release / "backend"))
    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from django.core.files.storage import storages
    from django.utils import timezone

    from apps.agent_api.models import BlogArticle, Document, KnowledgeBase, PrivateNote, PrivateNoteImage, UserProfile
    from apps.agent_api.services.rag import ingest_document

    user = get_user_model().objects.create_user(username="i019-operator", password="isolated-only-password")
    UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR, workspace_key="default")
    BlogArticle.objects.create(
        title="I019 release article",
        slug="i019-release-article",
        content="I019 durable release marker",
        status=BlogArticle.Status.PUBLISHED,
        published_at=timezone.now(),
    )
    note = PrivateNote.objects.create(owner=user, workspace_key="default", title="I019 private note")
    key = storages["private_note_media"].save(f"{user.pk}/i019.png", ContentFile(b"i019-private-image"))
    PrivateNoteImage.objects.create(owner=user, workspace_key="default", note=note, file=key)
    kb = KnowledgeBase.objects.create(name="i019-release-kb", workspace_key="default")
    document = Document.objects.create(
        knowledge_base=kb,
        workspace_key="default",
        title="I019 indexed document",
        content_text=QUERY,
    )
    ingest_document(document)
    document.refresh_from_db()
    require(document.status == Document.Status.READY, "Seed document was not indexed")
    print("seeded isolated article, private attachment, indexed document")


def http(base, path, method="GET", payload=None, token=None):
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(
        base + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=4) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


def wait_http(base, path, expected, process, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited before {path}: code={process.returncode}")
        try:
            response = http(base, path)
            if response[0] == expected:
                return response
        except (URLError, OSError):
            pass
        time.sleep(0.15)
    raise RuntimeError(f"Timed out waiting for {path} HTTP {expected}")


def start_server(release, data_root, port, log_path):
    log = log_path.open("wb")
    try:
        process = subprocess.Popen(
            [PYTHON, str(release / "backend" / "manage.py"), "runserver", "--noreload", f"127.0.0.1:{port}"],
            cwd=release / "backend",
            env=environment(data_root),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    finally:
        log.close()
    return process


def stop_server(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)


def verify_service(base):
    status, body, _ = http(base, "/api/health/")
    require(status == 200 and json.loads(body)["status"] == "ok", "Liveness failed")
    status, body, _ = http(base, "/api/ready/")
    require(status == 200 and json.loads(body)["status"] == "ready", "Readiness failed")
    status, body, kind = http(base, "/")
    require(status == 200 and "text/html" in kind and b'<div id="app"' in body, "SPA entry failed")
    match = re.search(rb'/assets/[^" ]+\.js', body)
    require(match is not None and http(base, match.group().decode())[0] == 200, "SPA JavaScript asset failed")
    status, body, _ = http(base, "/api/agent/blog/articles/i019-release-article/")
    require(status == 200 and b"I019 durable release marker" in body, "Article read failed")
    status, body, _ = http(
        base,
        "/api/agent/auth/login/",
        "POST",
        {"username": "i019-operator", "password": "isolated-only-password"},
    )
    require(status == 200, "Operator login failed")
    token = json.loads(body)["token"]
    image_path = "/api/agent/blog/notes/images/1/"
    require(http(base, image_path)[0] == 401, "Private image allowed anonymous read")
    status, body, _ = http(base, image_path, token=token)
    require(status == 200 and body == b"i019-private-image", "Private image read failed")
    status, body, _ = http(base, "/api/agent/knowledge-search/", "POST", {"query": QUERY}, token)
    require(
        status == 200 and any(item["document_title"] == "I019 indexed document" for item in json.loads(body)),
        "Indexed search failed",
    )
    return "liveness, readiness, SPA+JS, article, login, private 401/200, retrieval"


def add_failed_migration(release):
    directory = release / "backend" / "apps" / "agent_api" / "migrations"
    names = sorted(path.stem for path in directory.glob("[0-9][0-9][0-9][0-9]_*.py"))
    require(bool(names), "Cannot find agent_api migration leaf")
    previous = names[-1]
    injected = f"{int(previous[:4]) + 1:04d}_i019_injected_failure"
    (directory / f"{injected}.py").write_text(
        "from django.db import migrations\n\n"
        "def fail(apps, schema_editor):\n"
        "    raise RuntimeError('i019_isolated_migration_failure')\n\n"
        "class Migration(migrations.Migration):\n"
        f"    dependencies = [('agent_api', '{previous}')]\n"
        "    operations = [migrations.RunPython(fail)]\n",
        encoding="utf-8",
    )
    return injected


def migration_count(database):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute("SELECT COUNT(*) FROM django_migrations").fetchone()[0]


def unused_port():
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "seed":
        child_seed(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    require(len(sys.argv) == 1, "Usage: rehearse_deploy_rollback.py")
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="blog-i019-") as directory:
        base = Path(directory)
        release_a, release_b, data, preflight = (
            base / name for name in ("release-a", "release-b", "data", "preflight")
        )
        build_frontend(base / "frontend-build")
        copy_release(release_a, base / "frontend-build")
        release_a_hash = release_hash(release_a)
        data.mkdir()
        run_manage(release_a, data, "migrate", "--noinput", "--verbosity", "0")
        subprocess.run([PYTHON, __file__, "seed", str(release_a), str(data)], check=True, timeout=45)
        db_file = data / "db.sqlite3"
        before_migrations = migration_count(db_file)
        port = unused_port()
        address = f"http://127.0.0.1:{port}"
        server = None
        try:
            deploy_started = time.monotonic()
            server = start_server(release_a, data, port, base / "release-a.log")
            wait_http(address, "/api/ready/", 200, server)
            initial_checks = verify_service(address)
            print(f"release A deployed and verified in {time.monotonic() - deploy_started:.3f}s: " + initial_checks)

            shutil.copytree(release_a, release_b, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
            failed_migration = add_failed_migration(release_b)
            release_b_hash = release_hash(release_b)
            preflight.mkdir()
            with closing(sqlite3.connect(db_file)) as src, closing(sqlite3.connect(preflight / "db.sqlite3")) as dst:
                src.backup(dst)
            outcome = run_manage(release_b, preflight, "migrate", "--noinput", "--verbosity", "0", must_succeed=False)
            require(
                outcome.returncode != 0 and "i019_isolated_migration_failure" in outcome.stderr,
                "Failure injection did not stop migration",
            )
            require(migration_count(db_file) == before_migrations, "Live rehearsal database changed during preflight")
            print(f"candidate B preflight rejected: {failed_migration}; live schema unchanged")

            stop_server(server)
            server = start_server(release_b, data, port, base / "release-b.log")
            wait_http(address, "/api/health/", 200, server)
            status, body, _ = wait_http(address, "/api/ready/", 503, server)
            require(json.loads(body)["reason"] == "pending_migrations", "Candidate failed for an unexpected reason")
            print("candidate B live process: health=200 ready=503; promotion refused")

            rollback_started = time.monotonic()
            stop_server(server)
            server = start_server(release_a, data, port, base / "release-a-rollback.log")
            wait_http(address, "/api/ready/", 200, server)
            restored_checks = verify_service(address)
            require(migration_count(db_file) == before_migrations, "Schema changed across rollback")
            print(
                f"release A rolled back and verified in {time.monotonic() - rollback_started:.3f}s: " + restored_checks
            )
            print(
                f"git={git_sha} release_a_sha256={release_a_hash} release_b_sha256={release_b_hash} "
                f"frontend_dist_sha256={hashlib.sha256((release_a / 'frontend' / 'dist' / 'index.html').read_bytes()).hexdigest()} "
                f"config=settings_e2e local_hash/sqlite migrations={before_migrations} image=not_built"
            )
        finally:
            stop_server(server)


if __name__ == "__main__":
    main()
