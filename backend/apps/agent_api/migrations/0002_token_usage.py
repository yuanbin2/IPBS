from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_api", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="token_usage",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="message",
            name="token_usage",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

