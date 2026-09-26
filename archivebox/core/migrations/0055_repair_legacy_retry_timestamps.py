"""Repair SQLite queue timestamps written as raw ISO strings by old migrations."""

from django.db import migrations
from django.utils.dateparse import parse_datetime


def repair_legacy_retry_timestamps(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "sqlite":
        return

    with connection.cursor() as cursor:
        # 0024 created this Crawl already sealed, but left a due retry marker.
        # Its orphaned snapshots have their own scheduler rows for maintenance.
        cursor.execute(
            """
            UPDATE crawls_crawl SET retry_at = NULL
            WHERE status = 'sealed'
              AND label = 'Migrated from v0.7.2/v0.8.6'
              AND notes = 'Auto-created crawl for migrated snapshots'
              AND substr(retry_at, 11, 1) = 'T'
            """,
        )

        # SQLite compares stored date strings lexically. A raw `T` timestamp
        # from a legacy migration sorts differently from Django's space-separated
        # parameter, so a due row can be selected but never claimed. Preserve
        # the datetime Django already reads from each row while rewriting its
        # storage representation through the active database adapter.
        for table in ("crawls_crawl", "core_snapshot", "machine_binary", "machine_process"):
            last_id = ""
            while True:
                cursor.execute(
                    f"SELECT id, CAST(retry_at AS TEXT) FROM {table} WHERE id > %s AND substr(retry_at, 11, 1) = 'T' ORDER BY id LIMIT 500",
                    [last_id],
                )
                rows = cursor.fetchall()
                if not rows:
                    break
                for row_id, raw_retry_at in rows:
                    try:
                        parsed = parse_datetime(raw_retry_at)
                    except ValueError:
                        continue
                    if parsed is None:
                        continue
                    normalized = connection.ops.adapt_datetimefield_value(parsed)
                    cursor.execute(
                        f"UPDATE {table} SET retry_at = %s WHERE id = %s AND retry_at = %s",
                        [normalized, row_id, raw_retry_at],
                    )
                last_id = rows[-1][0]


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0054_snapshot_fs_version_index"),
    ]

    operations = [migrations.RunPython(repair_legacy_retry_timestamps, migrations.RunPython.noop)]
