import hashlib

from django.db import migrations, models


STASH_KEY = "__archivebox_0052_original_row"
TEMP_PLUGIN_PREFIX = "__abx52_"


def _temporary_plugin_name(row_id, reserved_plugins):
    salt = 0
    while True:
        digest = hashlib.sha256(f"{row_id}:{salt}".encode()).hexdigest()[:24]
        candidate = f"{TEMP_PLUGIN_PREFIX}{digest}"
        if candidate not in reserved_plugins:
            return candidate
        salt += 1


def stash_archiveresult_hook_rows(apps, schema_editor):
    """Make plugin names temporarily unique when reversing to 0053."""
    ArchiveResult = apps.get_model("core", "ArchiveResult")
    duplicate_groups = ArchiveResult.objects.values("snapshot_id", "plugin").annotate(count=models.Count("id")).filter(count__gt=1)
    for group in duplicate_groups.iterator(chunk_size=200):
        rows = list(
            ArchiveResult.objects.filter(snapshot_id=group["snapshot_id"], plugin=group["plugin"]).order_by("created_at", "id"),
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


def restore_archiveresult_hook_rows(apps, schema_editor):
    """Undo 0052's temporary plugin renames after its constraint is removed."""
    ArchiveResult = apps.get_model("core", "ArchiveResult")
    rows = ArchiveResult.objects.filter(plugin__startswith=TEMP_PLUGIN_PREFIX)
    for row in rows.iterator(chunk_size=200):
        stash = row.output_json
        original = stash.get(STASH_KEY) if isinstance(stash, dict) else None
        if not isinstance(original, dict) or "plugin" not in original:
            continue
        row.plugin = original["plugin"]
        row.output_json = original.get("output_json")
        row.save(update_fields=["plugin", "output_json"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0053_alter_archiveresult_options"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="archiveresult",
            name="unique_archiveresult_per_snapshot_plugin",
        ),
        migrations.RunPython(
            restore_archiveresult_hook_rows,
            reverse_code=stash_archiveresult_hook_rows,
        ),
        migrations.AddConstraint(
            model_name="archiveresult",
            constraint=models.UniqueConstraint(
                fields=("snapshot", "plugin", "hook_name"),
                name="unique_archiveresult_per_snapshot_hook",
            ),
        ),
    ]
