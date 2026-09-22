import django.db.models.fields.json
import django.db.models.functions.comparison
from django.db import migrations, models
from django.db.models import Q


VALID_PERMISSIONS = {"public", "unlisted", "private"}
BATCH_SIZE = 1000


def normalize_permissions(value, default="private"):
    value = str(value or "").strip().lower()
    return value if value in VALID_PERMISSIONS else default


def hydrate_snapshot_permissions(apps, schema_editor):
    Snapshot = apps.get_model("core", "Snapshot")
    db_alias = schema_editor.connection.alias
    missing_permissions = Q(permissions__isnull=True) | (Q(permissions__isnull=False) & ~Q(permissions__in=VALID_PERMISSIONS))
    batch = []

    snapshots = (
        Snapshot.objects.using(db_alias)
        .filter(missing_permissions)
        .select_related("crawl")
        .only("id", "config", "crawl__permissions")
        .iterator(chunk_size=BATCH_SIZE)
    )
    for snapshot in snapshots:
        config = dict(snapshot.config or {})
        config["PERMISSIONS"] = normalize_permissions(snapshot.crawl.permissions)
        snapshot.config = config
        batch.append(snapshot)
        if len(batch) >= BATCH_SIZE:
            Snapshot.objects.using(db_alias).bulk_update(batch, ["config"], batch_size=BATCH_SIZE)
            batch.clear()

    if batch:
        Snapshot.objects.using(db_alias).bulk_update(batch, ["config"], batch_size=BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("crawls", "0016_hydrate_crawl_permissions"),
        ("core", "0049_alter_snapshot_url"),
    ]

    operations = [
        migrations.RunPython(hydrate_snapshot_permissions, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="snapshot",
            name="permissions",
        ),
        migrations.AddField(
            model_name="snapshot",
            name="permissions",
            field=models.GeneratedField(
                db_index=True,
                db_persist=True,
                editable=False,
                expression=django.db.models.functions.comparison.Coalesce(
                    django.db.models.fields.json.KeyTextTransform("PERMISSIONS", "config"),
                    models.Value("private"),
                    output_field=models.CharField(max_length=16),
                ),
                output_field=models.CharField(max_length=16),
            ),
        ),
    ]
