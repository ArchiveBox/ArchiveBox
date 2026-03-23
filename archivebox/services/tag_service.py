from __future__ import annotations

from abx_dl.events import TagEvent
from abx_dl.services.base import BaseService

from .db import run_db_op


class TagService(BaseService):
    LISTENS_TO = [TagEvent]
    EMITS = []

    async def on_TagEvent__Outer(self, event: TagEvent) -> None:
        await run_db_op(self._project, event)

    def _project(self, event: TagEvent) -> None:
        from archivebox.core.models import Snapshot, Tag

        snapshot = Snapshot.objects.filter(id=event.snapshot_id).first()
        if snapshot is None:
            return
        Tag.from_json({"name": event.name}, overrides={"snapshot": snapshot})
