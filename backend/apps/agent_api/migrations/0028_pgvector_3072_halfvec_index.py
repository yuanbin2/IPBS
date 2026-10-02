from django.db import migrations


def use_halfvec_for_3072_hnsw(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        # Remove the old vector(3072) index definition if a database was
        # manually advanced past the migration that originally created it.
        cursor.execute("DROP INDEX IF EXISTS agent_api_vectorindex_embedding_3072_hnsw_idx")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS agent_api_vectorindex_embedding_3072_halfvec_hnsw_idx
            ON agent_api_vectorindex
            USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
            WHERE vector_dimensions = 3072
            """)


def remove_halfvec_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS agent_api_vectorindex_embedding_3072_halfvec_hnsw_idx")


class Migration(migrations.Migration):
    dependencies = [
        ("agent_api", "0027_conversationproject_conversation_project"),
    ]

    operations = [
        migrations.RunPython(use_halfvec_for_3072_hnsw, remove_halfvec_index),
    ]
