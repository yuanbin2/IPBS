"""Report legacy/mixed embedding identities and optionally quarantine unknown rows."""

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Count, Q

from apps.agent_api.models import EmbeddingRecord
from apps.agent_api.services.vector_store import PGVECTOR_TABLE

UNKNOWN_IDENTITY = (
    Q(provider__in=("", "legacy-unknown"))
    | Q(model_version__in=("", "unknown"))
    | Q(algorithm_version__in=("", "unknown"))
    | Q(corpus_version__in=("", "unknown"))
    | Q(index_version__in=("", "unknown"))
    | Q(model="")
)


class Command(BaseCommand):
    help = "Report vector-space identities; optionally quarantine records whose identity is unknown."

    def add_arguments(self, parser):
        parser.add_argument(
            "--quarantine-unknown",
            action="store_true",
            help="Mark ready records with incomplete identity as quarantined without deleting vector data.",
        )

    def handle(self, *args, **options):
        if options["quarantine_unknown"]:
            changed = (
                EmbeddingRecord.objects.filter(status=EmbeddingRecord.Status.READY)
                .filter(UNKNOWN_IDENTITY)
                .update(
                    status=EmbeddingRecord.Status.QUARANTINED,
                    fallback_reason="embedding_identity_incomplete",
                )
            )
            self.stdout.write(f"Quarantined ORM records: {changed}; vector data was retained.")
            self._quarantine_pgvector_rows()

        total = EmbeddingRecord.objects.count()
        unknown = EmbeddingRecord.objects.filter(UNKNOWN_IDENTITY).count()
        quarantined = EmbeddingRecord.objects.filter(status=EmbeddingRecord.Status.QUARANTINED).count()
        self.stdout.write(f"EmbeddingRecord total={total} incomplete_identity={unknown} quarantined={quarantined}")
        groups = (
            EmbeddingRecord.objects.values(
                "status",
                "provider",
                "model",
                "model_version",
                "algorithm_version",
                "vector_dimensions",
                "normalized",
                "corpus_version",
                "index_version",
            )
            .annotate(record_count=Count("id"))
            .order_by("status", "provider", "model", "model_version")
        )
        for group in groups:
            self.stdout.write(
                "space "
                + " ".join(f"{name}={group[name]}" for name in group if name != "record_count")
                + f" records={group['record_count']}"
            )

    def _quarantine_pgvector_rows(self):
        if connection.vendor != "postgresql":
            self.stdout.write("PostgreSQL vector index not changed (database vendor is not PostgreSQL).")
            return
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s)", [PGVECTOR_TABLE])
            if cursor.fetchone()[0] is None:
                self.stdout.write("PostgreSQL vector index table does not exist; nothing to quarantine.")
                return
            cursor.execute(f"""
                UPDATE {PGVECTOR_TABLE}
                SET status = 'quarantined', fallback_reason = 'embedding_identity_incomplete'
                WHERE status = 'ready'
                  AND (provider IN ('', 'legacy-unknown') OR model = ''
                       OR model_version IN ('', 'unknown')
                       OR algorithm_version IN ('', 'unknown')
                       OR corpus_version IN ('', 'unknown') OR index_version IN ('', 'unknown'))
                """)
            self.stdout.write(f"Quarantined pgvector rows: {cursor.rowcount}; vector data was retained.")
