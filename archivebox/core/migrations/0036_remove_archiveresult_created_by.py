# Generated migration

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0035_snapshot_crawl_non_nullable_remove_created_by'),
    ]

    operations = [
        # Remove created_by field from ArchiveResult
        # No data migration needed - created_by can be accessed via snapshot.crawl.created_by
        migrations.RemoveField(
            model_name='archiveresult',
            name='created_by',
        ),
    ]
