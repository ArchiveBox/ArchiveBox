# Add missing columns to ArchiveResult and remove created_by_id from Snapshot

from django.db import migrations, models, connection
import django.utils.timezone


def add_columns_if_not_exist(apps, schema_editor):
    """Add columns to ArchiveResult only if they don't already exist."""
    with connection.cursor() as cursor:
        # Get existing columns
        cursor.execute("PRAGMA table_info(core_archiveresult)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        # Add num_uses_failed if it doesn't exist
        if 'num_uses_failed' not in existing_columns:
            cursor.execute("ALTER TABLE core_archiveresult ADD COLUMN num_uses_failed integer unsigned NOT NULL DEFAULT 0 CHECK (num_uses_failed >= 0)")

        # Add num_uses_succeeded if it doesn't exist
        if 'num_uses_succeeded' not in existing_columns:
            cursor.execute("ALTER TABLE core_archiveresult ADD COLUMN num_uses_succeeded integer unsigned NOT NULL DEFAULT 0 CHECK (num_uses_succeeded >= 0)")

        # Add config if it doesn't exist
        if 'config' not in existing_columns:
            cursor.execute("ALTER TABLE core_archiveresult ADD COLUMN config text NULL")

        # Add retry_at if it doesn't exist
        if 'retry_at' not in existing_columns:
            cursor.execute("ALTER TABLE core_archiveresult ADD COLUMN retry_at datetime NULL")
            cursor.execute("CREATE INDEX IF NOT EXISTS core_archiveresult_retry_at_idx ON core_archiveresult(retry_at)")


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0037_remove_archiveresult_output_dir_and_more'),
    ]

    operations = [
        # Add missing columns to ArchiveResult
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='archiveresult',
                    name='num_uses_failed',
                    field=models.PositiveIntegerField(default=0),
                ),
                migrations.AddField(
                    model_name='archiveresult',
                    name='num_uses_succeeded',
                    field=models.PositiveIntegerField(default=0),
                ),
                migrations.AddField(
                    model_name='archiveresult',
                    name='config',
                    field=models.JSONField(blank=True, default=dict, null=True),
                ),
                migrations.AddField(
                    model_name='archiveresult',
                    name='retry_at',
                    field=models.DateTimeField(blank=True, db_index=True, default=django.utils.timezone.now, null=True),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_columns_if_not_exist, reverse_code=migrations.RunPython.noop),
            ],
        ),

        # Drop created_by_id from Snapshot (database only, already removed from model in 0035)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # No state changes - field already removed in 0035
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        -- Drop index first, then column
                        DROP INDEX IF EXISTS core_snapshot_created_by_id_6dbd6149;
                        ALTER TABLE core_snapshot DROP COLUMN created_by_id;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
