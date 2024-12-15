# Generated by Django 5.0.6 on 2024-08-18 06:46

import django.db.models.deletion
from django.db import migrations, models

def update_archiveresult_snapshot_ids(apps, schema_editor):
    ArchiveResult = apps.get_model("core", "ArchiveResult")
    Snapshot = apps.get_model("core", "Snapshot")
    num_total = ArchiveResult.objects.all().count()
    print(f'   Updating {num_total} ArchiveResult.snapshot_id values in place... (may take an hour or longer for large collections...)')
    for idx, result in enumerate(ArchiveResult.objects.all().only('snapshot_old_id').iterator(chunk_size=5000)):
        assert result.snapshot_old_id
        snapshot = Snapshot.objects.only('id').get(old_id=result.snapshot_old_id)
        result.snapshot_id = snapshot.id
        result.save(update_fields=["snapshot_id"])
        assert str(result.snapshot_id) == str(snapshot.id)
        if idx % 5000 == 0:
            print(f'Migrated {idx}/{num_total} ArchiveResult objects...')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0039_rename_snapshot_archiveresult_snapshot_old'),
    ]

    operations = [
        migrations.AddField(
            model_name='archiveresult',
            name='snapshot',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='archiveresults', to='core.snapshot', to_field='id'),
        ),
        migrations.RunPython(update_archiveresult_snapshot_ids, reverse_code=migrations.RunPython.noop),
    ]
