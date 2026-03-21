from __future__ import annotations

from asgiref.sync import sync_to_async
from django.utils import timezone

from abx_dl.events import CrawlCleanupEvent, CrawlCompletedEvent, CrawlSetupEvent, CrawlStartEvent
from abx_dl.services.base import BaseService


class CrawlService(BaseService):
    LISTENS_TO = [CrawlSetupEvent, CrawlStartEvent, CrawlCleanupEvent, CrawlCompletedEvent]
    EMITS = []

    def __init__(self, bus, *, crawl_id: str):
        self.crawl_id = crawl_id
        super().__init__(bus)

    async def on_CrawlSetupEvent(self, event: CrawlSetupEvent) -> None:
        await sync_to_async(self._mark_started, thread_sensitive=True)()

    async def on_CrawlStartEvent(self, event: CrawlStartEvent) -> None:
        await sync_to_async(self._mark_started, thread_sensitive=True)()

    async def on_CrawlCleanupEvent(self, event: CrawlCleanupEvent) -> None:
        await sync_to_async(self._mark_started, thread_sensitive=True)()

    async def on_CrawlCompletedEvent(self, event: CrawlCompletedEvent) -> None:
        await sync_to_async(self._mark_completed, thread_sensitive=True)()

    def _mark_started(self) -> None:
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.get(id=self.crawl_id)
        if crawl.status != Crawl.StatusChoices.SEALED:
            crawl.status = Crawl.StatusChoices.STARTED
        crawl.retry_at = None
        crawl.save(update_fields=["status", "retry_at", "modified_at"])

    def _mark_completed(self) -> None:
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.get(id=self.crawl_id)
        crawl.status = Crawl.StatusChoices.SEALED
        crawl.retry_at = None
        crawl.save(update_fields=["status", "retry_at", "modified_at"])
