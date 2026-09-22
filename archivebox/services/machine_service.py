from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async

from abx_dl.events import MachineEvent
from abx_dl.services.base import BaseService


def _is_binary_event_key(key: str) -> bool:
    """``MachineEvent`` projector only ever writes binary-related state.

    ``Machine.config`` mirrors ``ArchiveBox.conf`` so arbitrary user keys can
    legitimately live there — but they get there through the file ↔ DB sync,
    not through events. Letting events write arbitrary keys would let an
    untrusted plugin overwrite security-sensitive user config (the file ↔ DB
    mirror is a security boundary), so the projector strips anything that
    isn't a binary path or the binary install cache.
    """
    if key.startswith("ABX_") and key.endswith("CACHE"):
        return True
    return key.endswith("_BINARY")


def _strip_to_binary_keys(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    return {key: value for key, value in config.items() if _is_binary_event_key(str(key))}


class MachineService(BaseService):
    LISTENS_TO = [MachineEvent]
    EMITS = []

    def __init__(self, bus):
        super().__init__(bus)
        self.bus.on(MachineEvent, self.on_MachineEvent__save_to_db)

    async def on_MachineEvent__save_to_db(self, event: MachineEvent) -> None:
        from archivebox.machine.models import Machine

        if event.config_type != "derived":
            return

        machine = await sync_to_async(Machine.current, thread_sensitive=True)()
        old_config = dict(machine.config or {})
        config = dict(old_config)

        if event.config is not None:
            binary_only = _strip_to_binary_keys(event.config)
            config.update(binary_only)
        elif event.method == "update":
            key = event.key.replace("config/", "", 1).strip()
            if key and _is_binary_event_key(key):
                config[key] = event.value
        elif event.method == "unset":
            key = event.key.replace("config/", "", 1).strip()
            if key and _is_binary_event_key(key):
                config.pop(key, None)
        else:
            return

        if config == old_config:
            return
        machine.config = config
        await machine.asave(update_fields=["config", "modified_at"])
