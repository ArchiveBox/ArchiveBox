from django.db import migrations, models


def deduplicate_archiveresults_per_hook(apps, schema_editor):
    """Drop duplicate modern ArchiveResult rows per hook.

    Real long-lived collections (cabbage's demo, beta-tester DBs) accumulated
    multiple rows per hook over the dev rc chain. The next operation adds a
    conditional UniqueConstraint on that tuple; without this cleanup pass the
    constraint fails with ``UNIQUE constraint failed`` mid-migration and bricks
    startup. Legacy rows all have an empty hook_name and represent extractor
    history, so preserve them. Keep the row with the highest id for each modern
    non-empty hook.
    """
    ArchiveResult = apps.get_model("core", "ArchiveResult")
    duplicate_groups = (
        ArchiveResult.objects.exclude(hook_name="")
        .values("snapshot_id", "plugin", "hook_name")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
    )
    for group in duplicate_groups.iterator(chunk_size=200):
        lookup = {
            "snapshot_id": group["snapshot_id"],
            "plugin": group["plugin"],
            "hook_name": group["hook_name"],
        }
        keep = ArchiveResult.objects.filter(**lookup).order_by("-id").values_list("id", flat=True).first()
        if keep is not None:
            ArchiveResult.objects.filter(**lookup).exclude(id=keep).delete()


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
                condition=~models.Q(hook_name=""),
                name="unique_archiveresult_per_snapshot_hook",
            ),
        ),
    ]
