"""Copy legacy local blog images into private S3 storage without deleting sources."""

from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError

from apps.agent_api.services.blog_media import is_blog_image_name, sha256_file, validate_blog_image


class Command(BaseCommand):
    help = "Validate and copy legacy media/blog images into the configured blog_media storage."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help="Legacy MEDIA_ROOT directory to read (never modified).")
        parser.add_argument("--dry-run", action="store_true", help="Validate and report without uploading.")
        parser.add_argument(
            "--exclude",
            action="append",
            default=[],
            help="Explicitly leave a reviewed legacy filename out of the copy; repeat as needed.",
        )

    def handle(self, *args, **options):
        storage_config = settings.STORAGES["blog_media"]
        if storage_config["BACKEND"] != "storages.backends.s3.S3Storage":
            raise CommandError("BLOG_MEDIA_STORAGE must be s3 before migrating to the bucket.")

        source_dir = Path(options["source"]).expanduser().resolve() / "blog"
        if not source_dir.is_dir():
            raise CommandError(f"Legacy image directory does not exist: {source_dir}")
        candidates = sorted(path for path in source_dir.iterdir() if is_blog_image_name(path.name))
        storage = storages["blog_media"]
        copied = skipped = 0
        excluded = set(options["exclude"])
        unknown_exclusions = excluded - {path.name for path in candidates}
        if unknown_exclusions:
            raise CommandError("Excluded filename(s) not found: " + ", ".join(sorted(unknown_exclusions)))

        prepared = []
        failures = []
        for source_path in candidates:
            if source_path.name in excluded:
                self.stdout.write(f"explicitly excluded (source retained): {source_path.name}")
                continue
            if source_path.is_symlink() or not source_path.is_file():
                failures.append(f"Refusing non-regular source image: {source_path}")
                continue
            try:
                with source_path.open("rb") as source:
                    validate_blog_image(source, source_path.name, decode_frames=True)
                    source_hash = sha256_file(source)
                    data = source.read()
                prepared.append((source_path, source_hash, data))
            except (OSError, ValueError) as exc:
                failures.append(f"Invalid legacy image {source_path}: {exc}")
        if failures:
            raise CommandError("Preflight failed; no bucket objects were written:\n" + "\n".join(failures))

        for source_path, source_hash, data in prepared:
            object_name = f"blog/{source_path.name}"
            if storage.exists(object_name):
                with storage.open(object_name, "rb") as existing:
                    existing_hash = sha256_file(existing)
                if existing_hash != source_hash:
                    raise CommandError(f"Object already exists with different content: {object_name}")
                skipped += 1
                self.stdout.write(f"verified existing {object_name} sha256={source_hash}")
                continue

            if options["dry_run"]:
                self.stdout.write(f"would copy {object_name} sha256={source_hash}")
                continue

            storage.save(object_name, ContentFile(data))
            with storage.open(object_name, "rb") as uploaded:
                validate_blog_image(uploaded, source_path.name, decode_frames=True)
                uploaded_hash = sha256_file(uploaded)
            if uploaded_hash != source_hash:
                raise CommandError(f"Uploaded object checksum mismatch: {object_name}")
            copied += 1
            self.stdout.write(f"copied and verified {object_name} sha256={source_hash}")

        suffix = " (dry run; no objects written)" if options["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(f"Complete: copied={copied}, already_verified={skipped}{suffix}"))
