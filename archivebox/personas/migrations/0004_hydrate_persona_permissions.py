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
    """Backfill the ``permissions`` generated column on ``personas_persona``.

    Long-lived dev DBs have ``personas/0003_persona_permissions`` marked
    applied in ``django_migrations`` but the historical migration with that
    name predates the current GeneratedField design — the column never made
    it onto the table. Without this guard, the hydration query below fails
    with ``no such column: personas_persona.permissions``. Fresh installs
    already have the column, so this is a no-op on first-time setup.
    """
    # ``table_info`` hides generated columns (SQLite docs: "this command
    # does not include the generated columns"). Fresh installs add
    # ``permissions`` as a STORED GeneratedField via 0003, which
    # ``table_xinfo`` reports but ``table_info`` does not — so the latter
    # would lie to us and we'd try to ALTER an already-present column.
    cursor.execute("PRAGMA table_xinfo(personas_persona)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "permissions" in existing_cols:
        return
    # See crawls/0016 — SQLite ALTER TABLE only allows VIRTUAL generated
    # columns; the runtime model's STORED declaration only applies to fresh
    # installs where the column lands during initial table creation.
    cursor.execute(
        "ALTER TABLE personas_persona "
        "ADD COLUMN permissions varchar(16) "
        "GENERATED ALWAYS AS (json_extract(config, '$.PERMISSIONS')) VIRTUAL",
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS personas_persona_permissions_idx ON personas_persona (permissions)",
    )


def hydrate_persona_permissions(apps, schema_editor):
    # sqlite-only legacy hydration + generated-column repair (PRAGMA
    # table_xinfo / VIRTUAL generated column). On postgres the ``permissions``
    # column is created portably by 0003 (AddField GeneratedField) and there is
    # never legacy data to hydrate, so this is a no-op there.
    if schema_editor.connection.vendor != "sqlite":
        return
    Persona = apps.get_model("personas", "Persona")
    base_config = raw_base_config(apps)
    default_permissions = resolve_permissions(base_config, "public")
    table_name = schema_editor.quote_name(Persona._meta.db_table)
    cursor = schema_editor.connection.cursor()
    _ensure_permissions_column(cursor)
    batch = []
    missing_permissions = Q(permissions__isnull=True) | (Q(permissions__isnull=False) & ~Q(permissions__in=VALID_PERMISSIONS))

    for persona in Persona.objects.filter(missing_permissions).iterator(chunk_size=BATCH_SIZE):
        config = dict(persona.config or {})
        resolved = dict(base_config)
        resolved.update(config)
        config["PERMISSIONS"] = resolve_permissions(resolved, default_permissions)
        batch.append((persona.id, config))
        if len(batch) >= BATCH_SIZE:
            flush_batch(cursor, table_name, batch)
            batch.clear()

    flush_batch(cursor, table_name, batch)


class Migration(migrations.Migration):
    dependencies = [
        ("machine", "0019_single_active_runner_constraint"),
        ("personas", "0003_persona_permissions"),
    ]

    operations = [
        migrations.RunPython(hydrate_persona_permissions, migrations.RunPython.noop),
    ]
