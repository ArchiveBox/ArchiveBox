from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0059_revoke_exposed_replay_sessions"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="snapshot",
            index=models.Index(fields=["status", "modified_at"], name="snapshot_status_modified_idx"),
        ),
    ]
