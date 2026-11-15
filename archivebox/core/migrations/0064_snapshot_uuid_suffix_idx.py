from django.db import migrations, models

from archivebox.uuid_compat import UUIDSuffix


class Migration(migrations.Migration):
    dependencies = [("core", "0063_smart_folder_rules")]

    operations = [
        migrations.AddIndex(
            model_name="snapshot",
            index=models.Index(UUIDSuffix("id"), name="snapshot_uuid_suffix_idx"),
        ),
    ]
