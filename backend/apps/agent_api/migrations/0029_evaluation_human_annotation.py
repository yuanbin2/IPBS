from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0028_pgvector_3072_halfvec_index")]

    operations = [
        migrations.AddField(
            model_name="evaluationcase",
            name="annotation",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
