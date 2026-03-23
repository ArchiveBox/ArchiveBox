from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0032_remove_archiveresult_retry_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="archiveresult",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("started", "Started"),
                    ("backoff", "Waiting to retry"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("skipped", "Skipped"),
                    ("noresults", "No Results"),
                ],
                db_index=True,
                default="queued",
                max_length=16,
            ),
        ),
    ]
