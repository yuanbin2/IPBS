from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agent_api", "0020_create_pgvector_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="blogarticle",
            name="author_name",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
    ]
