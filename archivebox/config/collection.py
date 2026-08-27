__package__ = "archivebox.config"

import io
import json
import os
from collections.abc import Mapping
from typing import Any

from archivebox.config.constants import CONSTANTS
from archivebox.config.configset import CaseConfigParser, decode_config_inputs
from archivebox.misc.logging import AttrDict


CONFIG_FILE_HEADER = (
    "# This is the config file for your ArchiveBox collection.\n"
    "#\n"
    "# You can add options here manually in INI format, or automatically by running:\n"
    "#    archivebox config --set KEY=VALUE\n"
    "#\n"
    "# This file is kept in sync 1:1 with Machine.config in the index DB —\n"
    "# editing either side propagates to the other. ``archivebox init`` reads\n"
    "# this file on startup; the admin Machine.config editor writes both.\n"
    "#\n"
    "# Full reference:\n"
    "#    https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration\n"
    "\n"
)


# Recursion guard for the bidirectional file<->DB mirror. Bidirectional sync
# means a write on one side always triggers an update on the other; without
# this flag, ``Machine.save -> mirror to file -> write_config_file -> mirror
# back to Machine -> Machine.save -> ...`` would loop forever. Module-level
# scalar is fine here — daphne handles each request on its own thread and the
# admin/CLI write paths are inherently serialized through the DB.
_MIRROR_IN_PROGRESS: bool = False
# One-time-per-process startup sync, gated so subsequent ``Machine.current()``
# calls collapse to a single boolean check.
_INITIAL_SYNC_DONE: bool = False


def _coerce_to_str_dict(config: Any) -> dict[str, str]:
    """Project an arbitrary config payload to flat ``{UPPER_KEY: str}`` form.

    INI files only round-trip strings, so we normalize Machine.config values
    to strings on the way out and accept the same shape on the way back.
    Pydantic re-coerces types at read time inside ``get_config``.

    Composite values (``dict`` / ``list`` / ``tuple``) are JSON-encoded so
    they round-trip back through pydantic-settings — ``str(some_dict)``
    would produce Python's repr (``{'k': 'v'}`` with single quotes), and
    pydantic-settings refuses to parse that as a ``dict`` field, causing
    e.g. ``ABX_INSTALL_CACHE`` to crash with ``ValidationError: Input
    should be a valid dictionary``.
    """
    if not config:
        return {}
    if not isinstance(config, Mapping):
        return {}
    flat: dict[str, str] = {}
    for key, value in config.items():
        upper_key = str(key).upper()
        if value is None:
            flat[upper_key] = ""
        elif isinstance(value, (dict, list, tuple)):
            flat[upper_key] = json.dumps(value, default=str)
        else:
            flat[upper_key] = str(value)
    return flat


def _load_file_config_dict() -> tuple[dict[str, str], float | None]:
    """Return ``(flat_dict, mtime)`` for ``ArchiveBox.conf`` (``({}, None)`` if missing)."""
    config_path = CONSTANTS.CONFIG_FILE
    try:
        mtime = config_path.stat().st_mtime
    except FileNotFoundError:
        return {}, None
    parser = CaseConfigParser()
    parser.read(config_path)
    flat = {key.upper(): value for section in parser.sections() for key, value in parser.items(section)}
    return flat, mtime


def _resolve_section_for_key(key: str, config_sections, plugin_configs) -> str:
    for section in config_sections.values():
        if key in type(section).model_fields:
            return section.toml_section_header
    for schema in plugin_configs.values():
        if "properties" in schema and key in schema["properties"]:
            return "PLUGINS"
    # Unknown / user-defined keys land in SERVER_CONFIG so we never lose them
    # (the previous code raised here, which was fine for the CLI-only path but
    # would break the mirror as soon as anyone added a plugin-tunable that
    # this process hasn't loaded a schema for).
    return "SERVER_CONFIG"


def _render_config_file_content(config: dict[str, str]) -> str:
    """Render a flat config dict to INI text, grouped by inferred section."""
    from archivebox.config.common import get_all_configs
    from archivebox.plugins.discovery import discover_plugin_configs

    config_sections = get_all_configs()
    plugin_configs = discover_plugin_configs()

    parser = CaseConfigParser()
    for key, val in sorted(config.items()):
        section = _resolve_section_for_key(key, config_sections, plugin_configs)
        if section not in parser:
            parser[section] = {}
        parser[section][key] = "" if val is None else str(val)

    buf = io.StringIO()
    buf.write(CONFIG_FILE_HEADER)
    parser.write(buf)
    return buf.getvalue()


def _write_file_if_changed(content: str) -> bool:
    """Atomic-write ``ArchiveBox.conf`` only when contents actually differ.

    Skipping unchanged writes is the difference between every Machine.save in
    a hot autodetection loop costing one disk write vs. zero.
    """
    from archivebox.misc.system import atomic_write

    config_path = CONSTANTS.CONFIG_FILE
    try:
        existing = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    except OSError:
        existing = None
    if existing == content:
        return False
    atomic_write(config_path, content)
    return True


def mirror_machine_config_to_file(config: Any) -> None:
    """Rewrite ``ArchiveBox.conf`` so it mirrors ``Machine.config`` exactly.

    Called from ``Machine.save`` after the row is committed. Recursion-guarded
    so the matching write_config_file -> Machine.save bounce doesn't loop.
    """
    global _MIRROR_IN_PROGRESS
    if _MIRROR_IN_PROGRESS:
        return
    _MIRROR_IN_PROGRESS = True
    try:
        flat = _coerce_to_str_dict(config)
        _write_file_if_changed(_render_config_file_content(flat))
    finally:
        _MIRROR_IN_PROGRESS = False


def _coerce_from_str_dict(file_config: dict[str, str]) -> dict[str, Any]:
    """Inverse of ``_coerce_to_str_dict``: decode complex INI values to native.

    ``mirror_machine_config_to_file`` JSON-encodes ``dict`` / ``list`` values
    so they round-trip through INI's string-only storage. When reading the
    file back into ``Machine.config`` (a JSONField that holds native types)
    those strings have to be decoded — otherwise downstream consumers like
    ``_emit_machine_config`` → ``MachineEvent`` → abx-dl see a JSON string
    where they expect a dict and raise ``TypeError``.
    Declared fields go through pydantic-settings' own ``field_is_complex`` /
    ``prepare_field_value`` so they're decoded per annotation. Undeclared
    keys (e.g. ``ABX_INSTALL_CACHE``, written dynamically by abx-dl) are
    JSON-decoded when their string starts with ``{`` or ``[`` — the same
    shape ``_coerce_to_str_dict`` writes them as.
    """
    from archivebox.config.common import ArchiveBoxConfig

    decoded = decode_config_inputs(ArchiveBoxConfig, file_config, decode_unknown_json=True)
    if not str(decoded.get("BASE_URL") or "").strip():
        from archivebox.config.common import base_url_from_legacy_server_config

        legacy_base_url = base_url_from_legacy_server_config(decoded)
        if legacy_base_url:
            decoded["BASE_URL"] = legacy_base_url
    return decoded


def _mirror_file_to_machine_config(file_config: dict[str, str]) -> None:
    """Copy ``ArchiveBox.conf`` contents into ``Machine.config``.

    Internal helper used by ``write_config_file`` and the startup sync —
    callers must hold the ``_MIRROR_IN_PROGRESS`` guard around it.
    """
    from archivebox.machine.models import Machine

    machine = Machine.current()
    if _coerce_to_str_dict(machine.config) == file_config:
        return
    machine.config = _coerce_from_str_dict(file_config)
    machine.save(update_fields=["config", "modified_at"])


def sync_machine_and_file(machine: Any = None) -> None:
    """One-time-per-process reconciliation between the two stores.

    Cheap on the common case where they already agree (single ``stat`` + dict
    compare ≈ 1ms). When the two sides diverge we merge them: each side's
    unique keys are preserved, and for keys present on both we let the newer
    side win (file mtime vs. ``Machine.modified_at``). After the merge both
    stores hold the union, so every subsequent write keeps them in lockstep
    via the full-replace mirror functions.

    Pass ``machine`` when the caller already has a current ``Machine``
    instance (e.g. from ``Machine.current()``) to skip the 10–15ms
    ``get_host_guid()`` round-trip on the cold path.
    """
    global _INITIAL_SYNC_DONE, _MIRROR_IN_PROGRESS
    if _INITIAL_SYNC_DONE:
        return
    _INITIAL_SYNC_DONE = True
    if _MIRROR_IN_PROGRESS:
        return
    _MIRROR_IN_PROGRESS = True
    try:
        if machine is None:
            from archivebox.machine.detect import get_host_guid
            from archivebox.machine.models import Machine

            try:
                machine = Machine.objects.filter(guid=get_host_guid()).first()
            except Exception:
                return
            if machine is None:
                return

        file_config, file_mtime = _load_file_config_dict()
        machine_config = _coerce_to_str_dict(machine.config)
        if machine_config == file_config:
            return

        db_mtime = machine.modified_at.timestamp() if machine.modified_at else 0.0
        file_is_newer = file_mtime is not None and file_mtime > db_mtime

        merged: dict[str, str] = {}
        all_keys = set(machine_config) | set(file_config)
        for key in all_keys:
            in_file = key in file_config
            in_db = key in machine_config
            if in_file and in_db:
                if file_config[key] == machine_config[key]:
                    merged[key] = file_config[key]
                else:
                    merged[key] = file_config[key] if file_is_newer else machine_config[key]
            elif in_file:
                merged[key] = file_config[key]
            else:
                merged[key] = machine_config[key]

        if merged != file_config:
            _write_file_if_changed(_render_config_file_content(merged))
        if merged != machine_config:
            machine.config = _coerce_from_str_dict(merged)
            machine.save(update_fields=["config", "modified_at"])
    finally:
        _MIRROR_IN_PROGRESS = False


def write_config_file(config: dict[str, str]) -> AttrDict:
    """Merge ``config`` into ``ArchiveBox.conf``, validate, then mirror to Machine.config.

    Backwards-compatible signature: callers (CLI ``archivebox config --set``
    and the init flow) pass a partial dict of keys to upsert.
    """

    from archivebox.config.common import get_all_configs
    from archivebox.plugins.discovery import discover_plugin_configs
    from archivebox.misc.system import atomic_write

    config_path = CONSTANTS.CONFIG_FILE

    if not os.access(config_path, os.F_OK):
        atomic_write(config_path, CONFIG_FILE_HEADER)

    config_file = CaseConfigParser()
    config_file.read(config_path)

    with open(config_path, encoding="utf-8") as old:
        atomic_write(f"{config_path}.bak", old.read())

    config_sections = get_all_configs()
    plugin_configs = discover_plugin_configs()

    # Set up sections in empty config file
    for key, val in config.items():
        section_name = _resolve_section_for_key(key, config_sections, plugin_configs)
        if section_name in config_file:
            existing_config = dict(config_file[section_name])
        else:
            existing_config = {}

        config_file[section_name] = AttrDict({**existing_config, key: val})

    with open(config_path, "w+", encoding="utf-8") as new:
        config_file.write(new)

    updated_config = {}
    try:
        # validate the updated_config by attempting to re-parse it
        from archivebox.config.common import get_config

        updated_config = get_config(include_machine=False).as_dict()
    except BaseException:  # lgtm [py/catch-base-exception]
        # something went horribly wrong, revert to the previous version
        with open(f"{config_path}.bak", encoding="utf-8") as old:
            atomic_write(config_path, old.read())

        raise

    if os.access(f"{config_path}.bak", os.F_OK):
        os.remove(f"{config_path}.bak")

    # Mirror the post-write file state into Machine.config so the DB stays
    # 1:1 with the on-disk file. Recursion-guarded so Machine.save's own
    # mirror-back doesn't loop us.
    global _MIRROR_IN_PROGRESS
    if not _MIRROR_IN_PROGRESS:
        _MIRROR_IN_PROGRESS = True
        try:
            flat, _mtime = _load_file_config_dict()
            _mirror_file_to_machine_config(flat)
        except Exception:
            pass
        finally:
            _MIRROR_IN_PROGRESS = False

    return AttrDict({key.upper(): updated_config.get(key.upper()) for key in config.keys()})
