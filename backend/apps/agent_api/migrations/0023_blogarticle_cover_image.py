from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agent_api", "0022_alter_blogarticle_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="blogarticle",
            name="cover_image",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
    ]