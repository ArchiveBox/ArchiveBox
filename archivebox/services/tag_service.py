from __future__ import annotations

from asgiref.sync import sync_to_async

from abx_dl.events import TagEvent
from abx_dl.services.base import BaseService


class TagService(BaseService):
    LISTENS_TO = [TagEvent]
    EMITS = []

    def __init__(self, bus):
        super().__init__(bus)
        self.bus.on(TagEvent, self.on_TagEvent__save_to_db)

    async def on_TagEvent__save_to_db(self, event: TagEvent) -> None:
        from archivebox.core.models import Snapshot, Tag

        snapshot = await Snapshot.objects.filter(id=event.snapshot_id).afirst()
        if snapshot is None:
            return
        tag, _ = await sync_to_async(Tag.get_or_create_by_name, thread_sensitive=True)(event.name)
        await sync_to_async(snapshot.add_tag_ids, thread_sensitive=True)([tag.pk])
