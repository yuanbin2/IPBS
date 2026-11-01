from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0048_agent_run_model_accounting")]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="request_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=36),
        ),
        migrations.AddField(
            model_name="agentrun", name="stage_timings", field=models.JSONField(blank=True, default=dict)
        ),
        migrations.AddField(
            model_name="documentingestionjob",
            name="request_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=36),
        ),
        migrations.AddField(
            model_name="documentingestionjob", name="timings", field=models.JSONField(blank=True, default=dict)
        ),
    ]
