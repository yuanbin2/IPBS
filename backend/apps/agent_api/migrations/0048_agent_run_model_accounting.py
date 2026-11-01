from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0047_chat_run_lifecycle")]

    operations = [
        migrations.AddField(model_name="agentrun", name="model_calls", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="agentrun", name="model_accounting", field=models.JSONField(blank=True, default=dict)),
    ]
