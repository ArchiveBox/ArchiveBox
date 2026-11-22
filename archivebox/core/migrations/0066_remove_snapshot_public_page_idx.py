from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0065_snapshot_public_page_idx")]

    # 0065 is now a no-op, including its state. Remove the physical index only
    # if an earlier release created it. Rolling back must not recreate it.
    operations = [
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS "snapshot_public_page_idx"',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
