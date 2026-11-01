"""Read-only reconciliation of database file references and managed storage keys."""

from dataclasses import dataclass

from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError

from ...models import Document, PrivateNoteImage
from ...services.blog_image_cleanup import referenced_blog_image_names
from ...services.blog_media import is_blog_image_name


@dataclass
class MediaAudit:
    missing: set[str]
    orphan: set[str]


def _files_under(storage, prefix):
    """List only application-managed prefixes; never traverse unrelated objects."""
    try:
        dirs, files = storage.listdir(prefix)
    except FileNotFoundError:
        return set()
    found = {f"{prefix}/{name}" for name in files}
    for name in dirs:
        found.update(_files_under(storage, f"{prefix}/{name}"))
    return found


def audit_media_references():
    public = storages["blog_media"]
    private = storages["private_note_media"]
    source = storages["default"]
    references = {
        "public": {f"blog/{name}" for name in referenced_blog_image_names()},
        "private": set(PrivateNoteImage.objects.exclude(file="").values_list("file", flat=True)),
        "source": set(Document.objects.exclude(source_file="").values_list("source_file", flat=True)),
    }
    inventories = {
        "public": {key for key in _files_under(public, "blog") if is_blog_image_name(key.rsplit("/", 1)[-1])},
        "private": _files_under(private, "private-notes"),
        "source": _files_under(source, "knowledge"),
    }
    # Private uploads currently use <user-id>/<uuid>.ext, while older files
    # may use private-notes/. Include numeric user directories without reading
    # any other private storage prefix.
    try:
        dirs, _ = private.listdir("")
    except FileNotFoundError:
        dirs = []
    for directory in dirs:
        if directory.isdecimal():
            inventories["private"].update(_files_under(private, directory))
    return {
        kind: MediaAudit(
            missing=keys - inventories[kind],
            orphan=inventories[kind] - keys,
        )
        for kind, keys in references.items()
    }


class Command(BaseCommand):
    help = "Read-only media reference audit; never deletes files or rows."

    def handle(self, *args, **options):
        try:
            results = audit_media_references()
        except Exception as exc:
            raise CommandError(f"Media audit failed; no changes made: {type(exc).__name__}") from exc
        for kind, result in results.items():
            self.stdout.write(f"{kind}: missing={len(result.missing)} orphan={len(result.orphan)}")
        self.stdout.write("Read-only audit; no files deleted. Review backup and references before any cleanup.")
