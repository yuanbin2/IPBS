"""Rehearse a complete, disposable SQLite + file restore; never reads live data.

Run from the repository root with .venv/Scripts/python backend/scripts/rehearse_backup_restore.py.
The production PostgreSQL/Bucket procedure is documented separately.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
QUERY = "recoverable sapphire atlas"
PUBLIC_IMAGE = "c" * 32 + ".png"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(root):
    return {
        str(path.relative_to(root)).replace("\\", "/"): _digest(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _child(stage, root):
    os.environ.update(
        DJANGO_SETTINGS_MODULE="config.settings_e2e",
        BLOG_LOCAL_MODE="true",
        E2E_DATA_ROOT=str(root),
        RAG_EMBEDDING_MODE="local_hash",
        RAG_VECTOR_BACKEND="sqlite",
        BLOG_MEDIA_STORAGE="file",
        PYTHON_DOTENV_DISABLED="1",
        LANGCHAIN_TRACING_V2="false",
        LANGSMITH_TRACING="false",
    )
    sys.path.insert(0, str(BACKEND))
    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from django.core.files.storage import storages
    from django.core.management import call_command
    from django.test import Client
    from django.utils import timezone

    from agent.security import issue_signed_token
    from apps.agent_api.management.commands.audit_media_references import audit_media_references
    from apps.agent_api.models import BlogArticle, Document, KnowledgeBase, PrivateNote, PrivateNoteImage, UserProfile
    from apps.agent_api.services.rag import ingest_document, search_knowledge_base

    if stage == "seed":
        call_command("migrate", verbosity=0)
        owner = get_user_model().objects.create_user(username="restore-owner")
        outsider = get_user_model().objects.create_user(username="restore-outsider")
        UserProfile.objects.create(user=owner, role=UserProfile.Role.VISITOR, workspace_key="restore-space")
        UserProfile.objects.create(user=outsider, role=UserProfile.Role.VISITOR, workspace_key="restore-space")
        storages["blog_media"].save("blog/" + PUBLIC_IMAGE, ContentFile(b"public-test-bytes"))
        BlogArticle.objects.create(
            title="Restore article",
            slug="restore-article",
            content=f"Published restore marker /media/blog/{PUBLIC_IMAGE}",
            status=BlogArticle.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        note = PrivateNote.objects.create(
            owner=owner, workspace_key="restore-space", title="Private restore note", content="owner only"
        )
        key = storages["private_note_media"].save("1/restore.png", ContentFile(b"private-test-bytes"))
        PrivateNoteImage.objects.create(
            owner=owner,
            workspace_key="restore-space",
            note=note,
            file=key,
            original_name="restore.png",
            byte_size=18,
            sha256=hashlib.sha256(b"private-test-bytes").hexdigest(),
        )
        kb = KnowledgeBase.objects.create(name="restore-kb", workspace_key="restore-space")
        document = Document.objects.create(knowledge_base=kb, workspace_key="restore-space", title="Restore document")
        document.source_file.save("restore.txt", ContentFile((QUERY + " is indexed.\n").encode()), save=True)
        ingest_document(document)
        document.refresh_from_db()
        assert document.status == Document.Status.READY, document.error_message
        assert search_knowledge_base(QUERY, workspace_key="restore-space")
        print(
            "seed: article=1 public_image=1 private_attachment=1 document=1 indexed_chunks=" + str(document.chunk_count)
        )
        return

    article = BlogArticle.objects.get(slug="restore-article")
    assert article.status == BlogArticle.Status.PUBLISHED and "restore marker" in article.content
    assert storages["blog_media"].open("blog/" + PUBLIC_IMAGE, "rb").read() == b"public-test-bytes"
    owner = get_user_model().objects.get(username="restore-owner")
    outsider = get_user_model().objects.get(username="restore-outsider")
    image = PrivateNoteImage.objects.get(owner=owner)
    assert image.note.owner_id == owner.pk and image.workspace_key == "restore-space"
    assert storages["private_note_media"].open(image.file.name, "rb").read() == b"private-test-bytes"
    client = Client(HTTP_HOST="localhost", HTTP_X_FORWARDED_PROTO="https")
    url = f"/api/agent/blog/notes/images/{image.pk}/"
    assert client.get(url).status_code == 401
    assert client.get(url, HTTP_AUTHORIZATION="Bearer " + issue_signed_token(outsider)).status_code == 404
    allowed = client.get(url, HTTP_AUTHORIZATION="Bearer " + issue_signed_token(owner))
    assert allowed.status_code == 200
    assert b"".join(allowed.streaming_content) == b"private-test-bytes"
    profile = UserProfile.objects.get(user=owner)
    profile.workspace_key = "other-space"
    profile.save(update_fields=["workspace_key"])
    assert client.get(url, HTTP_AUTHORIZATION="Bearer " + issue_signed_token(owner)).status_code == 404
    profile.workspace_key = "restore-space"
    profile.save(update_fields=["workspace_key"])
    document = Document.objects.get(title="Restore document")
    assert document.source_file.read().decode().startswith(QUERY)
    hits = search_knowledge_base(QUERY, workspace_key="restore-space")
    assert hits and hits[0].document_id == document.pk
    assert not search_knowledge_base(QUERY, workspace_key="other-space")
    audit = audit_media_references()
    assert all(not result.missing and not result.orphan for result in audit.values()), audit
    print(
        "verify: article, public/private bytes, 401/404/200 permissions, source, indexed retrieval, workspace isolation, orphan=0 missing=0"
    )


def main():
    if len(sys.argv) == 3 and sys.argv[1] in {"seed", "verify"}:
        _child(sys.argv[1], Path(sys.argv[2]))
        return
    if len(sys.argv) != 1:
        raise SystemExit("Usage: rehearse_backup_restore.py")
    started = time.perf_counter()
    env = dict(os.environ, PYTHON_DOTENV_DISABLED="1")
    with tempfile.TemporaryDirectory(prefix="blog-i011-") as temp:
        base = Path(temp)
        source, backup, restored = (base / name for name in ("source", "backup", "restored"))
        source.mkdir()
        backup.mkdir()
        restored.mkdir()
        subprocess.run([sys.executable, __file__, "seed", str(source)], cwd=BACKEND, env=env, check=True)
        backup_started = time.perf_counter()
        with (
            closing(sqlite3.connect(source / "db.sqlite3")) as src,
            closing(sqlite3.connect(backup / "db.sqlite3")) as dst,
        ):
            src.backup(dst)
        for folder in ("media", "private-notes"):
            if (source / folder).exists():
                shutil.copytree(source / folder, backup / folder)
        manifest = _manifest(backup)
        (backup / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        backup_seconds = time.perf_counter() - backup_started
        restore_started = time.perf_counter()
        shutil.copy2(backup / "db.sqlite3", restored / "db.sqlite3")
        for folder in ("media", "private-notes"):
            if (backup / folder).exists():
                shutil.copytree(backup / folder, restored / folder)
        assert _manifest(restored) == manifest, "Restored file hashes differ from backup manifest"
        subprocess.run([sys.executable, __file__, "verify", str(restored)], cwd=BACKEND, env=env, check=True)
        restore_seconds = time.perf_counter() - restore_started
        print(
            f"backup_seconds={backup_seconds:.3f} restore_and_verify_seconds={restore_seconds:.3f} total_seconds={time.perf_counter() - started:.3f}"
        )
        print(f"manifest_files={len(manifest)} isolated=True temporary_data_removed_on_exit=True")


if __name__ == "__main__":
    main()
