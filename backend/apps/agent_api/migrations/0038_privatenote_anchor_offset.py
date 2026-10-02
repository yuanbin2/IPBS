from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_api", "0037_blog_interaction_restrictions"),
    ]

    operations = [
        migrations.AddField(
            model_name="privatenote",
            name="anchor_offset",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
