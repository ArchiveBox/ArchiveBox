# Generated migration

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0035_snapshot_crawl_non_nullable_remove_created_by'),
    ]

    operations = [
        # Remove created_by field from ArchiveResult (state only)
        # No data migration needed - created_by can be accessed via snapshot.crawl.created_by
        # Leave created_by_id column in database (unused but harmless, avoids table rebuild)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='archiveresult',
                    name='created_by',
                ),
            ],
            database_operations=[
                # No database changes - leave created_by_id column in place to avoid table rebuild
            ],
        ),
    ]
