from django.db import migrations, models
from django.db.models import Sum


def consolidate_archiveresults_per_plugin(apps, schema_editor):
    ArchiveResult = apps.get_model("core", "ArchiveResult")
    Snapshot = apps.get_model("core", "Snapshot")
    duplicate_groups = ArchiveResult.objects.values("snapshot_id", "plugin").annotate(count=models.Count("id")).filter(count__gt=1)

    affected_snapshot_ids = set()
    for group in duplicate_groups.iterator(chunk_size=200):
        rows = list(
            ArchiveResult.objects.filter(
                snapshot_id=group["snapshot_id"],
                plugin=group["plugin"],
            ).order_by("created_at", "id"),
        )
        canonical = rows[0]
        winner = max(
            rows,
            key=lambda row: (
                bool(row.output_files),
                int(row.output_size or 0),
                row.modified_at,
                str(row.id),
            ),
        )
        output_files = {}
        mimetypes = set()
        for row in rows:
            output_files.update(row.output_files or {})
            mimetypes.update(part.strip() for part in (row.output_mimetypes or "").split(",") if part.strip())

        canonical.hook_name = winner.hook_name
        canonical.status = winner.status
        canonical.output_str = winner.output_str
        canonical.output_json = winner.output_json
        canonical.output_files = output_files
        canonical.output_size = max(
            sum(int(metadata.get("size") or 0) for metadata in output_files.values() if isinstance(metadata, dict)),
            *(int(row.output_size or 0) for row in rows),
        )
        canonical.output_mimetypes = ",".join(sorted(mimetypes))
        canonical.start_ts = min((row.start_ts for row in rows if row.start_ts), default=None)
        canonical.end_ts = max((row.end_ts for row in rows if row.end_ts), default=None)
        canonical.save(
            update_fields=[
                "hook_name",
                "status",
                "output_str",
                "output_json",
                "output_files",
                "output_size",
                "output_mimetypes",
                "start_ts",
                "end_ts",
            ],
        )
        ArchiveResult.objects.filter(id__in=[row.id for row in rows[1:]]).delete()
        affected_snapshot_ids.add(group["snapshot_id"])

    for snapshot_id in affected_snapshot_ids:
        total = ArchiveResult.objects.filter(snapshot_id=snapshot_id).aggregate(total=Sum("output_size"))["total"] or 0
        Snapshot.objects.filter(id=snapshot_id).update(output_size=total)


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
