from django.db import migrations


def freeze_existing_crawl_configs(apps, schema_editor):
    from archivebox.config.common import build_crawl_config_snapshot
    from archivebox.personas.models import Persona
    from django.contrib.auth import get_user_model

    Crawl = apps.get_model("crawls", "Crawl")
    User = get_user_model()
    db_alias = schema_editor.connection.alias

    for crawl in Crawl.objects.using(db_alias).select_related("persona", "created_by").iterator(chunk_size=200):
        current_config = dict(crawl.config or {})
        persona = Persona.objects.using(db_alias).filter(pk=crawl.persona_id).first()
        user = User.objects.using(db_alias).filter(pk=crawl.created_by_id).first()
        frozen_config = build_crawl_config_snapshot(
            user=user,
            persona=persona,
            overrides=current_config,
        )
        if frozen_config != current_config:
            Crawl.objects.using(db_alias).filter(pk=crawl.pk).update(config=frozen_config)


class Migration(migrations.Migration):
    dependencies = [
        ("crawls", "0017_drop_stale_crawl_limit_columns"),
    ]

    operations = [
        migrations.RunPython(freeze_existing_crawl_configs, migrations.RunPython.noop),
    ]
