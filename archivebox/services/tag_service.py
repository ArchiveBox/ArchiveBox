from __future__ import annotations

from abx_dl.events import TagEvent
from abx_dl.services.base import BaseService


class TagService(BaseService):
    LISTENS_TO = [TagEvent]
    EMITS = []

    def __init__(self, bus):
        super().__init__(bus)
        self.bus.on(TagEvent, self.on_TagEvent__save_to_db)

    async def on_TagEvent__save_to_db(self, event: TagEvent) -> None:
        from archivebox.core.models import Snapshot, SnapshotTag, Tag

        snapshot = await Snapshot.objects.filter(id=event.snapshot_id).afirst()
        if snapshot is None:
            return
        tag, _ = await Tag.objects.aget_or_create(name=event.name)
        await SnapshotTag.objects.aget_or_create(snapshot=snapshot, tag=tag)
