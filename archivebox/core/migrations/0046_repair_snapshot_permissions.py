from django.db import migrations


def _repair_snapshot_permissions(apps, schema_editor):
    """Backfill ``core_snapshot.permissions`` if a prior squash-skewed
    ``django_migrations`` row claimed ``0041_snapshot_permissions`` was
    applied but the column never actually landed on the table.

    Beta-tester / cabbage-style DBs upgraded incrementally through the
    0.8.x → 0.9.x rc chain have a 0041_snapshot_permissions entry with a
    different historical effect (the name was reused across squashes),
    so the runtime model's ``snapshot.permissions`` ``GeneratedField`` has
    no underlying column. Fresh installs added the column via 0041 and
    this is a no-op.
    """
    # sqlite-only legacy repair (PRAGMA table_xinfo + sqlite VIRTUAL generated
    # column syntax). On postgres the permissions column was created by 0041's
    # portable GeneratedField AddField (STORED generated column), so there is
    # nothing to repair.
    if schema_editor.connection.vendor != "sqlite":
        return

    cursor = schema_editor.connection.cursor()
    # ``table_xinfo`` lists STORED/VIRTUAL generated columns; ``table_info``
    # silently drops them, so a prior 0041 that landed the STORED column
    # would otherwise look absent here and we'd ALTER TABLE -> duplicate.
    cursor.execute("PRAGMA table_xinfo(core_snapshot)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "permissions" in existing_cols:
        return
    # See crawls/0016 — SQLite ALTER TABLE only allows VIRTUAL generated
    # columns; STORED would error with "cannot add a STORED column". The
    # runtime model's ``db_persist=True`` is only honored for fresh installs
    # where 0041 added the column during initial table creation.
    cursor.execute(
        "ALTER TABLE core_snapshot ADD COLUMN permissions varchar(16) GENERATED ALWAYS AS (json_extract(config, '$.PERMISSIONS')) VIRTUAL",
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS core_snapshot_permissions_idx ON core_snapshot (permissions)",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0045_archiveresult_unique_hook"),
    ]

    operations = [
        migrations.RunPython(_repair_snapshot_permissions, migrations.RunPython.noop),
    ]
