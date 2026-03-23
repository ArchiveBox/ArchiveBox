from __future__ import annotations

from abx_dl.events import CrawlCleanupEvent, CrawlCompletedEvent, CrawlSetupEvent, CrawlStartEvent
from abx_dl.services.base import BaseService

from .db import run_db_op


class CrawlService(BaseService):
    LISTENS_TO = [CrawlSetupEvent, CrawlStartEvent, CrawlCleanupEvent, CrawlCompletedEvent]
    EMITS = []

    def __init__(self, bus, *, crawl_id: str):
        self.crawl_id = crawl_id
        super().__init__(bus)

    async def on_CrawlSetupEvent__Outer(self, event: CrawlSetupEvent) -> None:
        await run_db_op(self._mark_started)

    async def on_CrawlStartEvent__Outer(self, event: CrawlStartEvent) -> None:
        await run_db_op(self._mark_started)

    async def on_CrawlCleanupEvent__Outer(self, event: CrawlCleanupEvent) -> None:
        await run_db_op(self._mark_started)

    async def on_CrawlCompletedEvent__Outer(self, event: CrawlCompletedEvent) -> None:
        await run_db_op(self._mark_completed)

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
