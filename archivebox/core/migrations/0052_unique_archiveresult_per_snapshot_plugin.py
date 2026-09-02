import hashlib

from django.db import migrations, models


STASH_KEY = "__archivebox_0052_original_row"
TEMP_PLUGIN_PREFIX = "__abx52_"


def _temporary_plugin_name(row_id, reserved_plugins):
    """Return a deterministic 32-character plugin name unused by this snapshot."""
    salt = 0
    while True:
        digest = hashlib.sha256(f"{row_id}:{salt}".encode()).hexdigest()[:24]
        candidate = f"{TEMP_PLUGIN_PREFIX}{digest}"
        if candidate not in reserved_plugins:
            return candidate
        salt += 1


def consolidate_archiveresults_per_plugin(apps, schema_editor):
    """Temporarily make plugin names unique without deleting hook history.

    This migration shipped with a short-lived one-row-per-plugin model, while
    0054 restores the durable (snapshot, plugin, hook_name) identity. Fresh
    upgrades still traverse both published migrations, so deleting duplicate
    rows here would lose history before 0054 gets a chance to restore the
    correct constraint. Rename only the non-canonical rows and stash their
    original plugin/output_json values for 0054 to restore verbatim.
    """
    ArchiveResult = apps.get_model("core", "ArchiveResult")
    duplicate_groups = ArchiveResult.objects.values("snapshot_id", "plugin").annotate(count=models.Count("id")).filter(count__gt=1)

    for group in duplicate_groups.iterator(chunk_size=200):
        rows = list(
            ArchiveResult.objects.filter(
                snapshot_id=group["snapshot_id"],
                plugin=group["plugin"],
            ).order_by("created_at", "id"),
        )
        winner = max(
            rows,
            key=lambda row: (
                bool(row.output_files),
                int(row.output_size or 0),
                row.modified_at,
                str(row.id),
            ),
        )
        reserved_plugins = set(
            ArchiveResult.objects.filter(snapshot_id=group["snapshot_id"]).values_list("plugin", flat=True),
        )
        for row in rows:
            if row.id == winner.id:
                continue
            temporary_plugin = _temporary_plugin_name(row.id, reserved_plugins)
            reserved_plugins.add(temporary_plugin)
            row.output_json = {
                STASH_KEY: {
                    "plugin": row.plugin,
                    "output_json": row.output_json,
                },
            }
            row.plugin = temporary_plugin
            row.save(update_fields=["plugin", "output_json"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0051_postgres_url_pattern_ops_index"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="archiveresult",
            name="unique_archiveresult_per_snapshot_hook",
        ),
        migrations.RunPython(
            consolidate_archiveresults_per_plugin,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="archiveresult",
            constraint=models.UniqueConstraint(
                fields=("snapshot", "plugin"),
                name="unique_archiveresult_per_snapshot_plugin",
            ),
        ),
    ]
