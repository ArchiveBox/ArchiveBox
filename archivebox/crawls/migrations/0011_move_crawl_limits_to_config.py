from django.db import migrations


def move_limit_fields_to_config(apps, schema_editor):
    Crawl = apps.get_model("crawls", "Crawl")
    rows = Crawl.objects.values("id", "config", "max_urls", "crawl_max_size", "snapshot_max_size").iterator(chunk_size=1000)
    for row in rows:
        config = dict(row["config"] or {})
        if row["max_urls"]:
            config["CRAWL_MAX_URLS"] = row["max_urls"]
        if row["crawl_max_size"]:
            config["CRAWL_MAX_SIZE"] = row["crawl_max_size"]
        if row["snapshot_max_size"]:
            config["SNAPSHOT_MAX_SIZE"] = row["snapshot_max_size"]
        if config != (row["config"] or {}):
            Crawl.objects.filter(id=row["id"]).update(config=config)


class Migration(migrations.Migration):
    dependencies = [
        ("crawls", "0010_crawl_delete_at"),
    ]

    operations = [
        migrations.RunPython(move_limit_fields_to_config, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="crawl",
            name="max_urls",
        ),
        migrations.RemoveField(
            model_name="crawl",
            name="crawl_max_size",
        ),
        migrations.RemoveField(
            model_name="crawl",
            name="snapshot_max_size",
        ),
    ]
