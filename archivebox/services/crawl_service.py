from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from abx_dl.events import CrawlCleanupEvent, CrawlCompletedEvent, CrawlSetupEvent, CrawlStartEvent
from abx_dl.services.base import BaseService
from archivebox.workers.models import ACTIVE_STATE_LEASE_SECONDS


class CrawlService(BaseService):
    """Project crawl phase changes without resurrecting paused or sealed work."""

    LISTENS_TO = [CrawlSetupEvent, CrawlStartEvent, CrawlCleanupEvent, CrawlCompletedEvent]
    EMITS = []

    def __init__(self, bus, *, crawl_id: str):
        self.crawl_id = crawl_id
        super().__init__(bus)
        for event_type in self.LISTENS_TO:
            self.bus.on(event_type, self.on_CrawlEvent__save_to_db)

    async def on_CrawlEvent__save_to_db(
        self,
        event: CrawlSetupEvent | CrawlStartEvent | CrawlCleanupEvent | CrawlCompletedEvent,
    ) -> None:
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

        status = Crawl.StatusChoices.STARTED
        retry_at = timezone.now()
        if isinstance(event, (CrawlSetupEvent, CrawlStartEvent)):
            retry_at += timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS)
        elif isinstance(event, CrawlCompletedEvent):
            crawl = await Crawl.objects.aget(id=self.crawl_id)
            if crawl.status in Crawl.INACTIVE_STATES:
                return
            if not await crawl.snapshot_set.filter(status__in=Snapshot.OPEN_STATES).aexists():
                status, retry_at = Crawl.StatusChoices.SEALED, None
        # Cleanup remains active: parser outputs may still be projected before
        # completion. Only completion can seal; every write rechecks cancellation.
        await (
            Crawl.objects.filter(id=self.crawl_id)
            .exclude(status__in=Crawl.INACTIVE_STATES)
            .aupdate(status=status, retry_at=retry_at, modified_at=timezone.now())
        )
