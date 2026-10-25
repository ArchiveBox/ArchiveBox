from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from abx_dl.events import CrawlCleanupEvent, CrawlCompletedEvent, CrawlSetupEvent, CrawlStartEvent
from abx_dl.services.base import BaseService
from archivebox.workers.models import ACTIVE_STATE_LEASE_SECONDS


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

        await (
            Crawl.objects.filter(id=self.crawl_id)
            .exclude(
                status__in=Crawl.INACTIVE_STATES,
            )
            .aupdate(
                status=Crawl.StatusChoices.STARTED,
                retry_at=timezone.now() + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS),
                modified_at=timezone.now(),
            )
        )

    async def on_CrawlStartEvent__save_to_db(self, event: CrawlStartEvent) -> None:
        from archivebox.crawls.models import Crawl

        await (
            Crawl.objects.filter(id=self.crawl_id)
            .exclude(
                status__in=Crawl.INACTIVE_STATES,
            )
            .aupdate(
                status=Crawl.StatusChoices.STARTED,
                retry_at=timezone.now() + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS),
                modified_at=timezone.now(),
            )
        )

    async def on_CrawlCleanupEvent__save_to_db(self, event: CrawlCleanupEvent) -> None:
        from archivebox.crawls.models import Crawl

        # Cleanup is still inside the active crawl lifecycle. Snapshot hooks may
        # have just written discovery output that the runner consumes before the
        # completion phase, so only the CrawlCompleted projection can retire
        # this execution. Runner shutdown must not substitute for that fact.
        await (
            Crawl.objects.filter(id=self.crawl_id)
            .exclude(
                status__in=Crawl.INACTIVE_STATES,
            )
            .aupdate(
                status=Crawl.StatusChoices.STARTED,
                retry_at=timezone.now(),
                modified_at=timezone.now(),
            )
        )

    async def on_CrawlCompletedEvent__save_to_db(self, event: CrawlCompletedEvent) -> None:
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.misc.util import sanitize_html_text
        from django.db.models import F, Value
        from django.db.models.functions import Concat

        crawl = await Crawl.objects.aget(id=self.crawl_id)
        if event.error:
            # abx-dl reports a settled failed execution through the same terminal
            # fact as a successful one. Preserve that error even when queued
            # children keep the crawl runnable; neither a seal nor a requeue
            # should silently turn the failed cleanup into success. Append in
            # SQL so a concurrent user's notes edit is not overwritten.
            error = sanitize_html_text(event.error)
            await (
                Crawl.objects.filter(id=self.crawl_id)
                .exclude(notes__contains=error)
                .aupdate(
                    notes=Concat(F("notes"), Value("\n"), Value(error)),
                    modified_at=timezone.now(),
                )
            )
        if crawl.is_paused or crawl.status == Crawl.StatusChoices.SEALED:
            return
        # A requested plugin run is outstanding work even on a sealed capture.
        # Completion of this execution must not discard a concurrently queued
        # request merely because its parent Snapshot already has a seal.
        is_finished = not await crawl.snapshot_set.filter(
            Q(status__in=Snapshot.OPEN_STATES) | Q(status=Snapshot.StatusChoices.SEALED, config__RETRY_PLUGINS__0__isnull=False),
        ).aexists()
        if not is_finished:
            await (
                Crawl.objects.filter(id=self.crawl_id)
                .exclude(
                    status__in=Crawl.INACTIVE_STATES,
                )
                .aupdate(
                    status=Crawl.StatusChoices.STARTED,
                    retry_at=timezone.now(),
                    modified_at=timezone.now(),
                )
            )
            return

        await (
            Crawl.objects.filter(id=self.crawl_id)
            .exclude(
                status__in=Crawl.INACTIVE_STATES,
            )
            .aupdate(
                status=Crawl.StatusChoices.SEALED,
                retry_at=None,
                modified_at=timezone.now(),
            )
        )
