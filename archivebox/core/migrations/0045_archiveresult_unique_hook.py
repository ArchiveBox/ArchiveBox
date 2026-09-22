from django.db import migrations, models


def deduplicate_archiveresults_per_hook(apps, schema_editor):
    """Give historical duplicate rows unique hook identities.

    Real long-lived collections (cabbage's demo, beta-tester DBs) accumulated
    multiple rows per hook. Preserve every row while keeping the newest row on
    the canonical hook identity expected by the current scheduler. Older rows
    receive deterministic historical identities before the existing unique
    constraint is added.
    """
    ArchiveResult = apps.get_model("core", "ArchiveResult")
    duplicate_groups = (
        ArchiveResult.objects.values("snapshot_id", "plugin", "hook_name").annotate(count=models.Count("id")).filter(count__gt=1)
    )
    for group in duplicate_groups.iterator(chunk_size=200):
        lookup = {
            "snapshot_id": group["snapshot_id"],
            "plugin": group["plugin"],
            "hook_name": group["hook_name"],
        }
        rows = list(ArchiveResult.objects.filter(**lookup).order_by("-id").values_list("id", flat=True))
        for row_id in rows[1:]:
            historical_name = f"__legacy_history__{row_id}"[:255]
            ArchiveResult.objects.filter(id=row_id).update(hook_name=historical_name)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0044_alter_archiveresult_status_alter_snapshot_status"),
    ]

    operations = [
        migrations.RunPython(
            deduplicate_archiveresults_per_hook,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="archiveresult",
            constraint=models.UniqueConstraint(
                fields=("snapshot", "plugin", "hook_name"),
                name="unique_archiveresult_per_snapshot_hook",
            ),
        ),
    ]
