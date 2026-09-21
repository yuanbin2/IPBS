from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0016_add_current_time_tool")]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="owner_username",
            field=models.CharField(db_index=True, default="anonymous", max_length=150),
        ),
    ]
