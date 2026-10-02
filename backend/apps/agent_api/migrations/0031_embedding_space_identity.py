from django.db import migrations, models


def quarantine_legacy_embeddings(apps, schema_editor):
    EmbeddingRecord = apps.get_model("agent_api", "EmbeddingRecord")
    EmbeddingRecord.objects.using(schema_editor.connection.alias).all().update(
        provider="legacy-unknown",
        model_version="unknown",
        algorithm_version="unknown",
        normalized=False,
        corpus_version="unknown",
        index_version="unknown",
        status="quarantined",
        fallback_reason="legacy_identity_unverified",
        embedded_at=None,
    )


def add_pgvector_identity_columns(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            ALTER TABLE agent_api_vectorindex
                ADD COLUMN IF NOT EXISTS provider varchar(120) NOT NULL DEFAULT 'legacy-unknown',
                ADD COLUMN IF NOT EXISTS model_version varchar(120) NOT NULL DEFAULT 'unknown',
                ADD COLUMN IF NOT EXISTS algorithm_version varchar(120) NOT NULL DEFAULT 'unknown',
                ADD COLUMN IF NOT EXISTS normalized boolean NOT NULL DEFAULT false,
                ADD COLUMN IF NOT EXISTS corpus_version varchar(120) NOT NULL DEFAULT 'unknown',
                ADD COLUMN IF NOT EXISTS index_version varchar(120) NOT NULL DEFAULT 'unknown',
                ADD COLUMN IF NOT EXISTS status varchar(24) NOT NULL DEFAULT 'quarantined',
                ADD COLUMN IF NOT EXISTS fallback_reason varchar(160) NOT NULL DEFAULT 'legacy_identity_unverified',
                ADD COLUMN IF NOT EXISTS embedded_at timestamptz
            """)
        cursor.execute("""
            UPDATE agent_api_vectorindex
            SET provider = 'legacy-unknown', model_version = 'unknown',
                algorithm_version = 'unknown', normalized = false,
                corpus_version = 'unknown', index_version = 'unknown',
                status = 'quarantined', fallback_reason = 'legacy_identity_unverified',
                embedded_at = NULL
            """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS agent_api_vectorindex_space_filter_idx
            ON agent_api_vectorindex
                (workspace_key, knowledge_base_id, provider, model, vector_dimensions)
            WHERE status = 'ready'
            """)


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0030_versioned_async_evaluations")]

    operations = [
        migrations.AddField(
            model_name="embeddingrecord",
            name="provider",
            field=models.CharField(default="legacy-unknown", max_length=120),
        ),
        migrations.AddField(
            model_name="embeddingrecord",
            name="model_version",
            field=models.CharField(default="unknown", max_length=120),
        ),
        migrations.AddField(
            model_name="embeddingrecord",
            name="algorithm_version",
            field=models.CharField(default="unknown", max_length=120),
        ),
        migrations.AddField(
            model_name="embeddingrecord",
            name="normalized",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="embeddingrecord",
            name="corpus_version",
            field=models.CharField(default="unknown", max_length=120),
        ),
        migrations.AddField(
            model_name="embeddingrecord",
            name="index_version",
            field=models.CharField(default="unknown", max_length=120),
        ),
        migrations.AddField(
            model_name="embeddingrecord",
            name="status",
            field=models.CharField(
                choices=[("ready", "Ready"), ("quarantined", "Quarantined"), ("needs_reindex", "Needs reindex")],
                db_index=True,
                default="quarantined",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="embeddingrecord",
            name="fallback_reason",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="embeddingrecord",
            name="embedded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(quarantine_legacy_embeddings, migrations.RunPython.noop),
        migrations.RunPython(add_pgvector_identity_columns, migrations.RunPython.noop),
    ]
