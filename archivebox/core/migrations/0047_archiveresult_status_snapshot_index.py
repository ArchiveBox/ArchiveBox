from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0046_repair_snapshot_permissions"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="CREATE INDEX IF NOT EXISTS archiveresult_status_snap_idx ON core_archiveresult (status, snapshot_id)",
                    reverse_sql="DROP INDEX IF EXISTS archiveresult_status_snap_idx",
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="archiveresult",
                    index=models.Index(fields=["status", "snapshot"], name="archiveresult_status_snap_idx"),
                ),
            ],
        ),
        migrations.RunSQL(
            sql="ANALYZE core_archiveresult",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
