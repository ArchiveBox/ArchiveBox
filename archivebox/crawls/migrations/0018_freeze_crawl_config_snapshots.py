import json

from django.db import migrations


BATCH_SIZE = 1000


def _config_cache_key(config):
    return json.dumps(config or {}, sort_keys=True, separators=(",", ":"), default=str)


def _flush_updates(Crawl, db_alias, pending):
    if pending:
        Crawl.objects.using(db_alias).bulk_update(pending, ["config"], batch_size=BATCH_SIZE)
        pending.clear()


def freeze_existing_crawl_configs(apps, schema_editor):
    from archivebox.config.common import build_crawl_config_snapshot
    from archivebox.config.constants import CONSTANTS
    from archivebox.personas.models import derive_persona_config

    class PersonaConfigSnapshot:
        def __init__(self, persona):
            self.name = persona.name
            self.config = dict(persona.config or {})

        def get_derived_config(self):
            return derive_persona_config(name=self.name, config=self.config, persona_dir=CONSTANTS.PERSONAS_DIR / self.name)

    Crawl = apps.get_model("crawls", "Crawl")
    Persona = apps.get_model("personas", "Persona")
    db_alias = schema_editor.connection.alias
    rows = Crawl.objects.using(db_alias).values_list("id", "persona_id", "config")
    persona_ids = {persona_id for _, persona_id, _ in rows if persona_id}
    personas = {persona.pk: PersonaConfigSnapshot(persona) for persona in Persona.objects.using(db_alias).filter(pk__in=persona_ids)}

    frozen_cache = {}
    pending = []
    for crawl_id, persona_id, current_config in rows.iterator(chunk_size=BATCH_SIZE):
        current_config = dict(current_config or {})
        cache_key = (persona_id, _config_cache_key(current_config))
        if cache_key not in frozen_cache:
            frozen_cache[cache_key] = build_crawl_config_snapshot(
                persona=personas.get(persona_id),
                overrides=current_config,
            )
        frozen_config = frozen_cache[cache_key]
        if frozen_config != current_config:
            pending.append(Crawl(id=crawl_id, config=frozen_config))
            if len(pending) >= BATCH_SIZE:
                _flush_updates(Crawl, db_alias, pending)

    _flush_updates(Crawl, db_alias, pending)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("crawls", "0017_drop_stale_crawl_limit_columns"),
    ]

    operations = [
        migrations.RunPython(freeze_existing_crawl_configs, migrations.RunPython.noop),
    ]
