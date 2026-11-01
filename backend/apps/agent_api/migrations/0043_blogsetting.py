from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agent_api", "0042_privatenote_private_images"),
    ]

    operations = [
        migrations.CreateModel(
            name="BlogSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("site_title", models.CharField(blank=True, default="", max_length=120)),
                ("site_tagline", models.CharField(blank=True, default="", max_length=200)),
                ("author_name", models.CharField(blank=True, default="", max_length=80)),
                ("about_title", models.CharField(blank=True, default="", max_length=120)),
                ("about_content", models.TextField(blank=True, default="")),
                ("about_highlights", models.JSONField(blank=True, default=list)),
                ("footer_text", models.CharField(blank=True, default="", max_length=200)),
                ("articles_per_page", models.PositiveIntegerField(default=12)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "站点设置",
                "verbose_name_plural": "站点设置",
            },
        ),
    ]
