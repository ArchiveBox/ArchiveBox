from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0053_alter_archiveresult_options"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="archiveresult",
            name="unique_archiveresult_per_snapshot_plugin",
        ),
        migrations.AddConstraint(
            model_name="archiveresult",
            constraint=models.UniqueConstraint(
                fields=("snapshot", "plugin", "hook_name"),
                name="unique_archiveresult_per_snapshot_hook",
            ),
        ),
    ]
