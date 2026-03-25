from __future__ import annotations

from asgiref.sync import sync_to_async

from abx_dl.events import MachineEvent
from abx_dl.services.base import BaseService


class MachineService(BaseService):
    LISTENS_TO = [MachineEvent]
    EMITS = []

    def __init__(self, bus):
        super().__init__(bus)
        self.bus.on(MachineEvent, self.on_MachineEvent__save_to_db)

    async def on_MachineEvent__save_to_db(self, event: MachineEvent) -> None:
        from archivebox.machine.models import Machine, _sanitize_machine_config

        machine = await sync_to_async(Machine.current, thread_sensitive=True)()
        config = dict(machine.config or {})

        if event.config is not None:
            config.update(_sanitize_machine_config(event.config))
        elif event.method == "update":
            key = event.key.replace("config/", "", 1).strip()
            if key:
                config[key] = event.value
        else:
            return

        machine.config = _sanitize_machine_config(config)
        await machine.asave(update_fields=["config", "modified_at"])
