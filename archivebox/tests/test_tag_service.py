import asyncio

import pytest

from abx_dl.events import TagEvent
from abx_dl.orchestrator import create_bus


pytestmark = pytest.mark.django_db(transaction=True)


def _create_snapshot():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    return Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )


def test_tag_event_projects_tag_to_snapshot():
    from archivebox.core.models import Tag
    from archivebox.services.tag_service import TagService

    snapshot = _create_snapshot()
    bus = create_bus(name="test_tag_service")
    TagService(bus)

    async def emit_tag_event() -> None:
        await bus.emit(
            TagEvent(
                name="example",
                snapshot_id=str(snapshot.id),
            ),
        )

    asyncio.run(emit_tag_event())

    snapshot.refresh_from_db()
    assert snapshot.tags.filter(name="example").exists()
    assert Tag.objects.filter(name="example").exists()
