from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0047_archiveresult_status_snapshot_index"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="archiveresult",
            name="config",
        ),
    ]
