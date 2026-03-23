from __future__ import annotations

from abx_dl.events import MachineEvent
from abx_dl.services.base import BaseService

from .db import run_db_op


class MachineService(BaseService):
    LISTENS_TO = [MachineEvent]
    EMITS = []

    async def on_MachineEvent__Outer(self, event: MachineEvent) -> None:
        await run_db_op(self._project, event)

    def _project(self, event: MachineEvent) -> None:
        from archivebox.machine.models import Machine

        machine = Machine.current()
        config = dict(machine.config or {})

        if event.config is not None:
            config.update(event.config)
        elif event.method == "update":
            key = event.key.replace("config/", "", 1).strip()
            if key:
                config[key] = event.value
        else:
            return

        machine.config = config
        machine.save(update_fields=["config", "modified_at"])
