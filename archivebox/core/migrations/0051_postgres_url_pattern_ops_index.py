# Postgres-only: btree pattern-ops index on core_snapshot.url so LIKE 'prefix%'
# queries (url__startswith and the URL prefix search) stay index scans under any
# database collation. SQLite needs nothing here: its plain url index already
# serves the bytewise range comparisons used on that backend.

from django.db import migrations


def add_pg_url_pattern_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS core_snapshot_url_pattern_ops_idx ON core_snapshot (url text_pattern_ops)",
    )


def remove_pg_url_pattern_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP INDEX IF EXISTS core_snapshot_url_pattern_ops_idx")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0050_snapshot_permissions_not_null"),
    ]

    operations = [
        migrations.RunPython(add_pg_url_pattern_index, remove_pg_url_pattern_index),
    ]
