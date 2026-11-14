from django.db import migrations, models
from archivebox.uuid_compat import uuid7


def create_inbox(apps, schema_editor):
    Folder = apps.get_model("core", "Folder")
    name = "📥 Inbox"
    if Folder.objects.filter(parent=None, name=name).exists():
        name = "📥 Inbox (smart)"
    Folder.objects.create(
        id=uuid7(),
        name=name,
        position=0,
        rules={"op": "NOT", "rules": [{"field": "folder", "lookup": "in_folder", "value": "*"}]},
    )


def normalize_parents(apps, schema_editor):
    Folder = apps.get_model("core", "Folder")
    Snapshot = apps.get_model("core", "Snapshot")
    Crawl = apps.get_model("crawls", "Crawl")
    for parent in list(Folder.objects.filter(children__isnull=False).distinct()):
        if Snapshot.objects.filter(folder=parent).exists() or Crawl.objects.filter(folder=parent).exists():
            name, suffix = "Items", 1
            while Folder.objects.filter(parent=parent, name=name).exists():
                suffix += 1
                name = f"Items ({suffix})"
            child = Folder.objects.create(id=uuid7(), parent=parent, name=name, created_by_id=parent.created_by_id)
            for model in (Snapshot, Crawl):
                while ids := list(model.objects.filter(folder=parent).values_list("pk", flat=True)[:500]):
                    model.objects.filter(pk__in=ids, folder=parent).update(folder=child)
        Folder.objects.filter(pk=parent.pk).update(rules={"field": "folder", "lookup": "in_children", "value": "self"})


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("core", "0062_snapshot_folders"), ("crawls", "0020_crawl_folder")]
    operations = [
        migrations.AddField(model_name="folder", name="rules", field=models.JSONField(null=True, blank=True, default=None)),
        migrations.RunPython(create_inbox, migrations.RunPython.noop),
        migrations.RunPython(normalize_parents, migrations.RunPython.noop),
    ]
