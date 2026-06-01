from django.db import migrations, models


def copy_template_config_to_schedule(apps, schema_editor):
    CrawlSchedule = apps.get_model("crawls", "CrawlSchedule")
    db_alias = schema_editor.connection.alias

    for schedule in CrawlSchedule.objects.using(db_alias).select_related("template").iterator(chunk_size=200):
        template_config = dict(schedule.template.config or {}) if schedule.template_id else {}
        CrawlSchedule.objects.using(db_alias).filter(pk=schedule.pk).update(config=template_config)


class Migration(migrations.Migration):
    dependencies = [
        ("crawls", "0018_freeze_crawl_config_snapshots"),
    ]

    operations = [
        migrations.AddField(
            model_name="crawlschedule",
            name="config",
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
        migrations.RunPython(copy_template_config_to_schedule, migrations.RunPython.noop),
    ]
