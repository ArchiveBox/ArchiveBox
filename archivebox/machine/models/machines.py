from __future__ import annotations

import socket
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.db import models
from django.utils import timezone

from archivebox.base_models.models import ModelWithHealthStats, normalize_config_json_values
from archivebox.machine import models as state
from archivebox.uuid_compat import CompactUUIDField, uuid7

from ..detect import get_host_guid, get_host_stats, get_os_info, get_vm_info
from .constants import MACHINE_RECHECK_INTERVAL

if TYPE_CHECKING:
    from .interfaces import NetworkInterface


def _sanitize_machine_config(config: dict[str, Any] | None, *, lib_dir: str | Path | None = None) -> dict[str, Any]:
    """Validate ``Machine.config`` in place.

    Drops stale ``*_BINARY`` overrides whose path no longer exists or whose
    path falls outside of ``ABXPKG_LIB_DIR`` (so a binary uninstall or a lib_dir
    move clears the override automatically). Non-``_BINARY`` keys
    (``BASE_URL``, ``SERVER_SECURITY_MODE``, plugin tunables, etc.) are
    pass-through — they're arbitrary config overrides and not ours to filter.
    """
    if not isinstance(config, dict):
        return {}

    sanitized = dict(config)
    active_lib_dir = Path(lib_dir).expanduser().absolute() if lib_dir else None
    for key, value in list(sanitized.items()):
        if not str(key).endswith("_BINARY"):
            continue
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not value:
            sanitized.pop(key, None)
            continue
        if "/" in value or value.startswith("~"):
            try:
                path = Path(value).expanduser()
                if not path.exists():
                    sanitized.pop(key, None)
                    continue
                if active_lib_dir is not None:
                    resolved_path = path.absolute()
                    try:
                        resolved_path.relative_to(active_lib_dir)
                    except ValueError:
                        sanitized.pop(key, None)
            except OSError:
                sanitized.pop(key, None)
    return sanitized


class MachineManager(models.Manager):
    def current(self) -> Machine:
        return Machine.current()


class Machine(ModelWithHealthStats):
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    guid = models.CharField(max_length=64, default=None, null=False, unique=True, editable=False)
    hostname = models.CharField(max_length=63, default=None, null=False)
    hw_in_docker = models.BooleanField(default=False, null=False)
    hw_in_vm = models.BooleanField(default=False, null=False)
    hw_manufacturer = models.CharField(max_length=63, default=None, null=False)
    hw_product = models.CharField(max_length=63, default=None, null=False)
    hw_uuid = models.CharField(max_length=255, default=None, null=False)
    os_arch = models.CharField(max_length=15, default=None, null=False)
    os_family = models.CharField(max_length=15, default=None, null=False)
    os_platform = models.CharField(max_length=63, default=None, null=False)
    os_release = models.CharField(max_length=63, default=None, null=False)
    os_kernel = models.CharField(max_length=255, default=None, null=False)
    stats = models.JSONField(default=dict, null=True, blank=True)
    config = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Machine-specific config overrides.",
    )
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    objects = MachineManager()  # pyright: ignore[reportIncompatibleVariableOverride]
    networkinterface_set: models.Manager[NetworkInterface]

    class Meta(ModelWithHealthStats.Meta):
        app_label = "machine"

    @classmethod
    def current(cls, refresh: bool = False) -> Machine:
        if refresh:
            state._CURRENT_MACHINE = None
        if state._CURRENT_MACHINE:
            if timezone.now() < state._CURRENT_MACHINE.modified_at + timedelta(seconds=MACHINE_RECHECK_INTERVAL):
                # One-time-per-process reconciliation between ArchiveBox.conf
                # and Machine.config. Fast-path: bool check + early-return when
                # the sync has already run, so the cached-machine return path
                # stays sub-microsecond.
                try:
                    from archivebox.config.collection import sync_machine_and_file

                    sync_machine_and_file(state._CURRENT_MACHINE)
                except Exception:
                    pass
                return state._CURRENT_MACHINE
            else:
                state._CURRENT_MACHINE = None

        host_guid = get_host_guid()
        try:
            state._CURRENT_MACHINE = cls.objects.get(guid=host_guid)
        except cls.DoesNotExist:
            config = {}
            try:
                from archivebox.config.collection import _coerce_from_str_dict, _load_file_config_dict

                file_config, _file_mtime = _load_file_config_dict()
                config = _coerce_from_str_dict(file_config)
            except Exception:
                config = {}
            state._CURRENT_MACHINE = cls.objects.create(
                guid=host_guid,
                hostname=socket.gethostname(),
                config=config,
                **get_os_info(),
                **get_vm_info(),
                stats=get_host_stats(),
            )
        else:
            if timezone.now() >= state._CURRENT_MACHINE.modified_at + timedelta(seconds=MACHINE_RECHECK_INTERVAL):
                for key, value in {
                    "hostname": socket.gethostname(),
                    **get_os_info(),
                    **get_vm_info(),
                    "stats": get_host_stats(),
                }.items():
                    setattr(state._CURRENT_MACHINE, key, value)
                state._CURRENT_MACHINE.save(
                    update_fields=[
                        "hostname",
                        "hw_in_docker",
                        "hw_in_vm",
                        "hw_manufacturer",
                        "hw_product",
                        "hw_uuid",
                        "os_arch",
                        "os_family",
                        "os_platform",
                        "os_release",
                        "os_kernel",
                        "stats",
                        "modified_at",
                    ],
                )
        machine = cls._sanitize_config(state._CURRENT_MACHINE)
        # Same one-time sync as the cached-return path. Triggers here on the
        # very first ``Machine.current()`` call in a process before any
        # cached return can occur.
        try:
            from archivebox.config.collection import sync_machine_and_file

            sync_machine_and_file(state._CURRENT_MACHINE)
        except Exception:
            pass
        return machine

    @classmethod
    def _sanitize_config(cls, machine: Machine) -> Machine:
        from archivebox.config.common import get_config

        sanitized = _sanitize_machine_config(machine.config, lib_dir=get_config(include_machine=False).ABXPKG_LIB_DIR)
        current = machine.config or {}
        if sanitized != current:
            machine.config = sanitized
            machine.save(update_fields=["config", "modified_at"])
        return machine

    def to_json(self) -> dict:
        """
        Convert Machine model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION
        from archivebox.config.common import redact_sensitive_config

        return {
            "type": "Machine",
            "schema_version": VERSION,
            "id": str(self.id),
            "guid": self.guid,
            "hostname": self.hostname,
            "hw_in_docker": self.hw_in_docker,
            "hw_in_vm": self.hw_in_vm,
            "hw_manufacturer": self.hw_manufacturer,
            "hw_product": self.hw_product,
            "hw_uuid": self.hw_uuid,
            "os_arch": self.os_arch,
            "os_family": self.os_family,
            "os_platform": self.os_platform,
            "os_kernel": self.os_kernel,
            "os_release": self.os_release,
            "stats": self.stats,
            "config": redact_sensitive_config(self.config),
        }

    @staticmethod
    def from_json(record: dict[str, Any], overrides: dict[str, Any] | None = None):
        """
        Update Machine config from JSON dict.

        Args:
            record: JSON dict with 'config': {key: value} patch
            overrides: Not used

        Returns:
            Machine instance or None
        """
        config_patch = _sanitize_machine_config(record.get("config"))
        if config_patch:
            machine = Machine.current()
            machine.config = _sanitize_machine_config(machine.config)
            machine.config.update(config_patch)
            machine.save(update_fields=["config"])
            return machine
        return None

    def save(self, *args, **kwargs):
        normalized_config = normalize_config_json_values(self.config)
        if normalized_config != self.config:
            self.config = normalized_config
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = tuple(dict.fromkeys([*update_fields, "config"]))

        # Drop the ``Machine.current()`` module-level cache on every save so
        # config edits (admin form, from_json, etc.) become live in the same
        # process without waiting out the 7-day ``MACHINE_RECHECK_INTERVAL``.
        # The cache reads ``state._CURRENT_MACHINE.modified_at`` and that value
        # never moves forward on the cached object even when the row is
        # updated in the DB, so without this we'd keep serving stale
        # ``machine.config`` (incl. ``BASE_URL``) until the worker restarts.
        update_fields = kwargs.get("update_fields")
        super().save(*args, **kwargs)
        if state._CURRENT_MACHINE is not None and state._CURRENT_MACHINE.pk == self.pk:
            state._CURRENT_MACHINE = None

        # Mirror Machine.config into ArchiveBox.conf so the two stores stay
        # 1:1. Skipped when ``update_fields`` is set and doesn't touch
        # ``config`` (binary autodetection + ``hostname``/``stats`` refreshes
        # save fields we don't need to disk-mirror, which keeps hot paths
        # zero-IO). Errors during mirroring are swallowed: the DB write
        # already succeeded and we don't want a config-file write hiccup to
        # turn a routine save into a 500.
        if update_fields is not None and "config" not in update_fields:
            return
        try:
            from archivebox.config.collection import mirror_machine_config_to_file

            mirror_machine_config_to_file(self.config)
        except Exception:
            pass
