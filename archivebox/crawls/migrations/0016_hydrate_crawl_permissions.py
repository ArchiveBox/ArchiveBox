import os
import json
import uuid

from django.db import migrations
from django.db.models import Q


VALID_PERMISSIONS = {"public", "unlisted", "private"}
BATCH_SIZE = 1000


def normalize_permissions(value, default):
    value = str(value or "").strip().lower()
    return value if value in VALID_PERMISSIONS else default


def raw_base_config(apps):
    try:
        from archivebox.config import CONSTANTS
        from archivebox.config.configset import BaseConfigSet

        config = {**BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE), **os.environ}
    except Exception:
        config = dict(os.environ)

    try:
        Machine = apps.get_model("machine", "Machine")
        machine_config = Machine.objects.order_by("-modified_at").values_list("config", flat=True).first() or {}
        if isinstance(machine_config, dict):
            config.update(machine_config)
    except Exception:
        pass
    return config


def resolve_permissions(config, default):
    from archivebox.config.common import permissions_from_legacy_public_flags

    explicit = str(config.get("PERMISSIONS") or "").strip().lower()
    if explicit in VALID_PERMISSIONS:
        return explicit
    return permissions_from_legacy_public_flags(config) or default


def id_values(pk):
    if isinstance(pk, uuid.UUID):
        return str(pk), pk.hex
    pk_str = str(pk)
    return pk_str, pk_str.replace("-", "")


def flush_batch(cursor, table_name, batch):
    if not batch:
        return
    cursor.executemany(
        f"UPDATE {table_name} SET config = %s WHERE id = %s OR id = %s",
        [(json.dumps(config), *id_values(pk)) for pk, config in batch],
    )


def _ensure_permissions_column(cursor):
    """Backfill the ``permissions`` generated column on ``crawls_crawl``.

    Long-lived dev DBs (cabbage's demo + beta-tester collections) have
    ``crawls/0013_crawl_permissions`` marked applied in ``django_migrations``
    but the *historical* migration with that name did something unrelated —
    the actual ``permissions`` column never made it onto the table. Without
    this guard the hydration query below fails with ``no such column:
    crawls_crawl.permissions`` and bricks startup. Fresh installs already
    have the column (added by the current 0013), so this is a safe no-op
    in that case.
    """
    # ``table_info`` hides generated columns (SQLite docs: "this command
    # does not include the generated columns"). Fresh installs add
    # ``permissions`` as a STORED GeneratedField via 0013, which
    # ``table_xinfo`` reports but ``table_info`` does not — so the latter
    # would lie to us and we'd try to ALTER an already-present column.
    cursor.execute("PRAGMA table_xinfo(crawls_crawl)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "permissions" in existing_cols:
        return
    # SQLite ``ALTER TABLE ADD COLUMN`` only supports VIRTUAL generated
    # columns (STORED is rejected with "cannot add a STORED column"). The
    # current model declares ``db_persist=True`` so fresh installs get a
    # STORED column via Django's initial table creation, but on legacy DBs
    # we have to settle for VIRTUAL — runtime behavior is equivalent (the
    # expression is evaluated on read instead of write), and Django's
    # field-level queries don't care which storage mode SQLite uses under
    # the hood. Index creation on a virtual column is still supported.
    cursor.execute(
        "ALTER TABLE crawls_crawl ADD COLUMN permissions varchar(16) GENERATED ALWAYS AS (json_extract(config, '$.PERMISSIONS')) VIRTUAL",
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS crawls_crawl_permissions_idx ON crawls_crawl (permissions)",
    )


def hydrate_crawl_permissions(apps, schema_editor):
    # sqlite-only legacy hydration + generated-column repair (PRAGMA
    # table_xinfo / VIRTUAL generated column). On postgres the ``permissions``
    # column is created portably by 0013 (AddField GeneratedField) and there is
    # never legacy data to hydrate, so this is a no-op there.
    if schema_editor.connection.vendor != "sqlite":
        return
    Crawl = apps.get_model("crawls", "Crawl")
    base_config = raw_base_config(apps)
    default_permissions = resolve_permissions(base_config, "public")
    table_name = schema_editor.quote_name(Crawl._meta.db_table)
    cursor = schema_editor.connection.cursor()
    _ensure_permissions_column(cursor)
    batch = []
    missing_permissions = Q(permissions__isnull=True) | (Q(permissions__isnull=False) & ~Q(permissions__in=VALID_PERMISSIONS))

    for crawl in Crawl.objects.filter(missing_permissions).select_related("persona").iterator(chunk_size=BATCH_SIZE):
        config = dict(crawl.config or {})
        resolved = dict(base_config)
        if crawl.persona_id:
            persona_config = crawl.persona.config or {}
            if isinstance(persona_config, dict):
                resolved.update(persona_config)
        resolved.update(config)
        config["PERMISSIONS"] = resolve_permissions(resolved, default_permissions)
        batch.append((crawl.id, config))
        if len(batch) >= BATCH_SIZE:
            flush_batch(cursor, table_name, batch)
            batch.clear()

    flush_batch(cursor, table_name, batch)


class Migration(migrations.Migration):
    dependencies = [
        ("machine", "0019_single_active_runner_constraint"),
        ("personas", "0004_hydrate_persona_permissions"),
        ("crawls", "0015_alter_crawl_status"),
    ]

    operations = [
        migrations.RunPython(hydrate_crawl_permissions, migrations.RunPython.noop),
    ]
