from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_api", "0003_knowledge_base_rag"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="sources",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="message",
            name="sources",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
