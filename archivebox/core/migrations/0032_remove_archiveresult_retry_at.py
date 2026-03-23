from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0031_add_archiveresult_snapshot_status_index"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="archiveresult",
            name="retry_at",
        ),
    ]
