from django.db import migrations, models


def freeze_existing_paths(apps, schema_editor):
    Destination = apps.get_model("storage", "StorageDestination")
    Run = apps.get_model("storage", "StorageRun")
    for destination in Destination.objects.using(schema_editor.connection.alias).iterator():
        Run.objects.using(schema_editor.connection.alias).filter(destination_id=destination.pk).update(destination_path=destination.path)


class Migration(migrations.Migration):
    dependencies = [("storage", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="storagedestination",
            name="config_revision",
            field=models.CharField(blank=True, default="", editable=False, max_length=32),
        ),
        migrations.AddField(
            model_name="storagerun",
            name="config_revision",
            field=models.CharField(blank=True, default="", editable=False, max_length=32),
        ),
        migrations.AddField(
            model_name="storagerun",
            name="destination_path",
            field=models.CharField(default="", max_length=2048),
            preserve_default=False,
        ),
        migrations.RunPython(freeze_existing_paths, migrations.RunPython.noop),
    ]
