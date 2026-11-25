"""Repair the SQLite tag association column left by 0.8 UUID-tag collections."""

import re

from django.db import migrations


def repair_snapshot_tag_id(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "sqlite":
        return

    with connection.cursor() as cursor:
        cursor.execute("PRAGMA table_info(core_snapshot_tags)")
        declared = {row[1]: row[2] for row in cursor.fetchall()}["tag_id"].lower()
        if declared == "integer":
            return

        # 0023 rewrote the tag references in place. Require canonical integer
        # strings before the affinity change can collapse values like '010'.
        cursor.execute(
            """
            SELECT membership.id
            FROM core_snapshot_tags AS membership
            LEFT JOIN core_tag AS tag ON tag.id = membership.tag_id
            WHERE tag.id IS NULL OR CAST(tag.id AS TEXT) != membership.tag_id
            LIMIT 1
            """,
        )
        if invalid := cursor.fetchone():
            raise ValueError(f"Invalid tag_id on core_snapshot_tags row {invalid[0]}")

        cursor.execute("SELECT sql FROM main.sqlite_master WHERE type = 'table' AND name = 'core_snapshot_tags'")
        column = rf'([,(]\s*(?:"tag_id"|tag_id)\s+){re.escape(declared)}(?=[\s,)])'
        ddl, matches = re.subn(column, r"\g<1>INTEGER", cursor.fetchone()[0], flags=re.IGNORECASE)
        if matches != 1 or not any(word in declared for word in ("char", "text", "clob")):
            raise ValueError(f"Unrecognized core_snapshot_tags.tag_id declaration: {declared}")

        # Preserve the installed constraints, indexes and triggers. Older
        # collections have an inline UNIQUE clause in place of a named index.
        cursor.execute(
            """
            SELECT sql FROM main.sqlite_master
            WHERE tbl_name = 'core_snapshot_tags' AND type IN ('index', 'trigger') AND sql IS NOT NULL
            ORDER BY rowid
            """,
        )
        objects = [row[0] for row in cursor.fetchall()]
        cursor.execute("SELECT seq FROM main.sqlite_sequence WHERE name = 'core_snapshot_tags'")
        sequence = cursor.fetchone()

        # The migration transaction rolls back both copies and DDL if copying
        # the rows, restoring an index, or checking the foreign keys fails.
        cursor.execute("CREATE TEMP TABLE saved_core_snapshot_tags AS SELECT * FROM main.core_snapshot_tags")
        cursor.execute("SELECT COUNT(*) FROM temp.saved_core_snapshot_tags")
        (original_count,) = cursor.fetchone()
        cursor.execute("DROP TABLE main.core_snapshot_tags")
        cursor.execute(ddl)
        cursor.execute("INSERT INTO main.core_snapshot_tags SELECT * FROM temp.saved_core_snapshot_tags")
        if cursor.rowcount != original_count:
            raise ValueError(f"Copied {cursor.rowcount} of {original_count} core_snapshot_tags rows")
        for sql in objects:
            cursor.execute(sql)
        if sequence is not None:
            # The high-water mark can be ahead of MAX(id), even on an empty table.
            cursor.execute("DELETE FROM main.sqlite_sequence WHERE name = 'core_snapshot_tags'")
            cursor.execute("INSERT INTO main.sqlite_sequence (name, seq) VALUES ('core_snapshot_tags', %s)", sequence)
        cursor.execute("PRAGMA foreign_key_check(core_snapshot_tags)")
        if violation := cursor.fetchone():
            raise ValueError(f"Foreign key violation in core_snapshot_tags: {violation}")
        cursor.execute("DROP TABLE temp.saved_core_snapshot_tags")


class Migration(migrations.Migration):
    dependencies = [("core", "0067_snapshot_reversed_domain")]
    operations = [migrations.RunPython(repair_snapshot_tag_id, migrations.RunPython.noop)]
