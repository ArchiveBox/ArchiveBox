from __future__ import annotations

from asgiref.sync import sync_to_async
from abx_dl.events import TagEvent
from abx_dl.services.base import BaseService


class TagService(BaseService):
    LISTENS_TO = [TagEvent]
    EMITS = []

    async def on_TagEvent(self, event: TagEvent) -> None:
        await sync_to_async(self._project, thread_sensitive=True)(event)

    def _project(self, event: TagEvent) -> None:
        from archivebox.core.models import Snapshot, Tag

        snapshot = Snapshot.objects.filter(id=event.snapshot_id).first()
        if snapshot is None:
            return
        Tag.from_json({"name": event.name}, overrides={"snapshot": snapshot})
