from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("agent_api", "0002_token_usage"),
    ]

    operations = [
        migrations.CreateModel(
            name="KnowledgeBase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("source_file", models.FileField(blank=True, upload_to="knowledge/")),
                ("content_type", models.CharField(blank=True, max_length=120)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("ready", "Ready"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=24,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                ("chunk_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "knowledge_base",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="agent_api.knowledgebase",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="DocumentChunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chunk_index", models.PositiveIntegerField()),
                ("content", models.TextField()),
                ("token_estimate", models.PositiveIntegerField(default=0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="agent_api.document",
                    ),
                ),
                (
                    "knowledge_base",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="agent_api.knowledgebase",
                    ),
                ),
            ],
            options={
                "ordering": ["document_id", "chunk_index"],
                "unique_together": {("document", "chunk_index")},
            },
        ),
        migrations.CreateModel(
            name="EmbeddingRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("model", models.CharField(max_length=120)),
                ("vector", models.JSONField(default=list)),
                ("vector_dimensions", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "chunk",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="embedding_record",
                        to="agent_api.documentchunk",
                    ),
                ),
            ],
            options={
                "ordering": ["chunk_id"],
            },
        ),
    ]
