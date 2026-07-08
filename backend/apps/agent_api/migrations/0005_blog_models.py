from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("agent_api", "0004_agentic_sources"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="content_text",
            field=models.TextField(blank=True),
        ),
        migrations.CreateModel(
            name="ArticleCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, unique=True)),
                ("slug", models.SlugField(allow_unicode=True, max_length=100, unique=True)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="ArticleTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60, unique=True)),
                ("slug", models.SlugField(allow_unicode=True, max_length=80, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="BlogArticle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("slug", models.SlugField(allow_unicode=True, max_length=220, unique=True)),
                ("summary", models.TextField(blank=True)),
                ("content", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("published", "Published"),
                            ("archived", "Archived"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("view_count", models.PositiveIntegerField(default=0)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="articles",
                        to="agent_api.articlecategory",
                    ),
                ),
                (
                    "knowledge_document",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="blog_articles",
                        to="agent_api.document",
                    ),
                ),
                ("tags", models.ManyToManyField(blank=True, related_name="articles", to="agent_api.articletag")),
            ],
            options={
                "ordering": ["-published_at", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="BlogComment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("author_name", models.CharField(max_length=80)),
                ("content", models.TextField()),
                ("is_approved", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="agent_api.blogarticle",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
    ]
