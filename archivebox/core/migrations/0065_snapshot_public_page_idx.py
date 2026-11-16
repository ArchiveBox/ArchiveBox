from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0064_snapshot_uuid_suffix_idx")]

    operations = [
        migrations.AddIndex(
            model_name="snapshot",
            index=models.Index(fields=["permissions", "-bookmarked_at", "-created_at", "id"], name="snapshot_public_page_idx"),
        ),
    ]
