from django.db import migrations


LEGACY_COLUMNS = ("max_urls", "crawl_max_size", "snapshot_max_size")


def drop_stale_crawl_limit_columns(apps, schema_editor):
    """Drop legacy NOT-NULL limit columns left over from pre-0011 schemas.

    crawls/0011_move_crawl_limits_to_config copies these fields into
    ``crawl.config`` and ``RemoveField``s them from the model. That works on
    fresh installs, but on collections where a *historical* 0011 ran (a
    different migration with the same id that pre-dates the current move-
    to-config logic) ``django_migrations`` records it as applied while the
    columns themselves stayed on the table as ``NOT NULL`` with no default.

    The next time anything tries to create a Crawl via the ORM (e.g. the
    /add/ form) Django doesn't pass those columns — they're not in the
    model — and SQLite raises ``NOT NULL constraint failed: crawls_crawl
    .max_urls``, which surfaces as an HTTP 500 on /add/. We hit this in
    the rc51 cabbage UI test before this migration existed.

    Self-heal: introspect the live table, copy any pre-existing values
    into ``config`` (so we don't drop data), then ``DROP COLUMN`` each
    legacy field. Fresh installs already have the columns removed and
    this is a no-op.
    """
    table_name = "crawls_crawl"
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = {column.name for column in connection.introspection.get_table_description(cursor, table_name)}
        stale_present = [col for col in LEGACY_COLUMNS if col in columns]
        if not stale_present:
            return
        # Backfill config with any non-null values from the stale columns so
        # nothing gets silently dropped. ``CRAWL_MAX_URLS`` / ``CRAWL_MAX_SIZE``
        # / ``SNAPSHOT_MAX_SIZE`` are the canonical config keys.
        col_to_config_key = {
            "max_urls": "CRAWL_MAX_URLS",
            "crawl_max_size": "CRAWL_MAX_SIZE",
            "snapshot_max_size": "SNAPSHOT_MAX_SIZE",
        }
        select_cols = ", ".join(schema_editor.quote_name(c) for c in stale_present)
        cursor.execute(f"SELECT id, config, {select_cols} FROM {schema_editor.quote_name(table_name)}")
        rows = cursor.fetchall()
        import json

        Crawl = apps.get_model("crawls", "Crawl")
        for row in rows:
            crawl_id, config_raw = row[0], row[1]
            stale_values = row[2:]
            try:
                config = dict(json.loads(config_raw)) if isinstance(config_raw, str) else dict(config_raw or {})
            except (TypeError, ValueError):
                config = {}
            mutated = False
            for col_name, value in zip(stale_present, stale_values, strict=False):
                if value in (None, 0, "0", ""):
                    continue
                key = col_to_config_key.get(col_name)
                if key and key not in config:
                    config[key] = value
                    mutated = True
            if mutated:
                Crawl.objects.filter(id=crawl_id).update(config=config)
        for col_name in stale_present:
            schema_editor.execute(
                f"ALTER TABLE {schema_editor.quote_name(table_name)} DROP COLUMN {schema_editor.quote_name(col_name)}",
            )


class Migration(migrations.Migration):
    dependencies = [
        ("crawls", "0016_hydrate_crawl_permissions"),
    ]

    operations = [
        migrations.RunPython(drop_stale_crawl_limit_columns, migrations.RunPython.noop),
    ]
