from __future__ import annotations

from abx_dl.events import CrawlCleanupEvent, CrawlCompletedEvent, CrawlSetupEvent, CrawlStartEvent
from abx_dl.services.base import BaseService


class CrawlService(BaseService):
    LISTENS_TO = [CrawlSetupEvent, CrawlStartEvent, CrawlCleanupEvent, CrawlCompletedEvent]
    EMITS = []

    def __init__(self, bus, *, crawl_id: str):
        self.crawl_id = crawl_id
        super().__init__(bus)
        self.bus.on(CrawlSetupEvent, self.on_CrawlSetupEvent__save_to_db)
        self.bus.on(CrawlStartEvent, self.on_CrawlStartEvent__save_to_db)
        self.bus.on(CrawlCleanupEvent, self.on_CrawlCleanupEvent__save_to_db)
        self.bus.on(CrawlCompletedEvent, self.on_CrawlCompletedEvent__save_to_db)

    async def on_CrawlSetupEvent__save_to_db(self, event: CrawlSetupEvent) -> None:
        from archivebox.crawls.models import Crawl

        crawl = await Crawl.objects.aget(id=self.crawl_id)
        if crawl.status != Crawl.StatusChoices.SEALED:
            crawl.status = Crawl.StatusChoices.STARTED
        crawl.retry_at = None
        await crawl.asave(update_fields=["status", "retry_at", "modified_at"])

    async def on_CrawlStartEvent__save_to_db(self, event: CrawlStartEvent) -> None:
        from archivebox.crawls.models import Crawl

        crawl = await Crawl.objects.aget(id=self.crawl_id)
        if crawl.status != Crawl.StatusChoices.SEALED:
            crawl.status = Crawl.StatusChoices.STARTED
        crawl.retry_at = None
        await crawl.asave(update_fields=["status", "retry_at", "modified_at"])

    async def on_CrawlCleanupEvent__save_to_db(self, event: CrawlCleanupEvent) -> None:
        from archivebox.crawls.models import Crawl

        crawl = await Crawl.objects.aget(id=self.crawl_id)
        if crawl.status != Crawl.StatusChoices.SEALED:
            crawl.status = Crawl.StatusChoices.STARTED
        crawl.retry_at = None
        await crawl.asave(update_fields=["status", "retry_at", "modified_at"])

    async def on_CrawlCompletedEvent__save_to_db(self, event: CrawlCompletedEvent) -> None:
        from archivebox.crawls.models import Crawl

        crawl = await Crawl.objects.aget(id=self.crawl_id)
        crawl.status = Crawl.StatusChoices.SEALED
        crawl.retry_at = None
        await crawl.asave(update_fields=["status", "retry_at", "modified_at"])
