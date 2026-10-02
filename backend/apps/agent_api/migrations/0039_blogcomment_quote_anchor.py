from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0038_privatenote_anchor_offset")]

    operations = [
        migrations.AddField(
            model_name="blogcomment",
            name="quote",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="blogcomment",
            name="anchor_offset",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
