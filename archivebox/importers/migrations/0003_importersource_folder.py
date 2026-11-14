from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("importers", "0002_importerrun_reset_code"),
        ("core", "0062_snapshot_folders"),
    ]

    operations = [
        migrations.AddField(
            model_name="importersource",
            name="folder",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="importer_sources",
                to="core.folder",
            ),
        ),
    ]
