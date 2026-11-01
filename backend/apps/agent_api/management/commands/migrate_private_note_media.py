"""Move legacy private note images out of the publicly served MEDIA_ROOT.

Run without --apply first to inspect. Database file names stay unchanged.
"""

import hashlib
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError

from apps.agent_api.models import PrivateNoteImage


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Command(BaseCommand):
    help = "Relocate legacy private note files from public media/private-notes to private storage."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Copy, verify and remove legacy files")

    def handle(self, *args, **options):
        legacy_root = (Path(settings.MEDIA_ROOT) / "private-notes").resolve()
        storage = storages["private_note_media"]
        target_root = Path(getattr(storage, "location", "")).resolve()
        if not str(getattr(storage, "location", "")):
            raise CommandError("Private note storage must be a local filesystem for this command")
        if target_root.is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
            raise CommandError("Private note target is still under public MEDIA_ROOT")

        moved = existing = missing = 0
        for image in PrivateNoteImage.objects.only("file", "sha256").iterator():
            name = Path(image.file.name)
            if name.is_absolute() or ".." in name.parts:
                raise CommandError(f"Unsafe file name for image {image.pk}")
            source = (legacy_root / name).resolve()
            target = (target_root / name).resolve()
            if not source.is_relative_to(legacy_root) or not target.is_relative_to(target_root):
                raise CommandError(f"Image {image.pk} escaped a storage root")
            if target.exists():
                if image.sha256 and sha256_file(target) != image.sha256:
                    raise CommandError(f"Private target checksum mismatch for image {image.pk}")
                if source.is_file():
                    if sha256_file(source) != sha256_file(target):
                        raise CommandError(f"Legacy and private copies differ for image {image.pk}")
                    if options["apply"]:
                        source.unlink()
                existing += 1
                continue
            if not source.is_file():
                missing += 1
                continue
            if image.sha256 and sha256_file(source) != image.sha256:
                raise CommandError(f"Legacy source checksum mismatch for image {image.pk}")
            if options["apply"]:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".migrating")
                shutil.copy2(source, temporary)
                if sha256_file(temporary) != sha256_file(source):
                    temporary.unlink(missing_ok=True)
                    raise CommandError(f"Copy verification failed for image {image.pk}")
                os.replace(temporary, target)
                source.unlink()
            moved += 1

        mode = "moved" if options["apply"] else "would move"
        self.stdout.write(f"{mode}: {moved}; already private: {existing}; missing: {missing}")
        if missing:
            raise CommandError("Some image files are missing; investigate before considering migration complete")
