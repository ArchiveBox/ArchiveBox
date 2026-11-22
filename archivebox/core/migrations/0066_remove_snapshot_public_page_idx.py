from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0065_snapshot_public_page_idx")]

    # The existing order index gives reasonable public-page performance without
    # maintaining another composite index on every snapshot write. See 0065's
    # index-reuse policy; exact display totals are not a reason to add indexes.
    # 0065 is now a no-op, including its state. Remove the physical index only
    # if an earlier release created it. Rolling back must not recreate it.
    operations = [
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS "snapshot_public_page_idx"',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
