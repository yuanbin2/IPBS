"""Preview or remove aged, unreferenced generated public blog images."""

from datetime import timedelta

from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ...services.blog_image_cleanup import referenced_blog_image_names
from ...services.blog_media import is_blog_image_name


class Command(BaseCommand):
    help = "Preview orphan public blog images; --apply deletes only files older than the grace period."

    def add_arguments(self, parser):
        parser.add_argument("--older-than-days", type=int, default=30)
        parser.add_argument("--apply", action="store_true", help="Delete eligible files; default is dry run")

    def handle(self, *args, **options):
        days = options["older_than_days"]
        if days < 1:
            raise CommandError("--older-than-days must be at least 1")
        cutoff = timezone.now() - timedelta(days=days)
        try:
            referenced = referenced_blog_image_names()
            storage = storages["blog_media"]
            _, files = storage.listdir("blog")
        except FileNotFoundError:
            files = []
        except Exception as exc:
            raise CommandError(f"Cannot inspect blog images; no files deleted: {exc}") from exc

        candidates = []
        skipped = 0
        for filename in files:
            if not is_blog_image_name(filename) or filename in referenced:
                continue
            key = f"blog/{filename}"
            try:
                modified = storage.get_modified_time(key)
                if timezone.is_naive(modified):
                    modified = timezone.make_aware(modified)
            except Exception:
                skipped += 1
                continue
            if modified < cutoff:
                candidates.append(key)

        self.stdout.write(
            f"Unreferenced images older than {days} days: {len(candidates)}; "
            f"metadata unavailable: {skipped}; mode: {'delete' if options['apply'] else 'preview'}"
        )
        for key in candidates[:20]:
            self.stdout.write(key)
        if not options["apply"]:
            self.stdout.write("No files deleted. Re-run with --apply after reviewing this preview.")
            return

        # Re-read references just before deletion to avoid using an old snapshot
        # after a potentially long object-store listing.
        try:
            referenced = referenced_blog_image_names()
        except Exception as exc:
            raise CommandError(f"Cannot recheck references; no files deleted: {exc}") from exc
        deleted = 0
        failed = 0
        for key in candidates:
            if key.rsplit("/", 1)[-1] in referenced:
                continue
            try:
                storage.delete(key)
                deleted += 1
            except Exception as exc:
                failed += 1
                self.stderr.write(f"Failed to delete {key}: {exc}")
        self.stdout.write(f"Deleted: {deleted}; failed: {failed}")
