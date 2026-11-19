"""The gallery's native homepage rule is exact, temporary, and runner-visible."""

import asyncio

import pytest

from archivebox.api.models import OutboundWebhook
from archivebox.core.library_screenshots import homepage_capture_budget
from archivebox.core.models import Folder, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.services.runner import CrawlRunner


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("capture_fails", [False, True])
def test_homepage_budget_is_exact_and_cleaned_up(capture_fails):
    homepage = "http://127.0.0.1:8999/"
    urls = [homepage, homepage + "story", homepage + "?page=2", "http://localhost:8999/"]
    Folder.objects.create(name="Existing gallery folder")
    previous = OutboundWebhook.objects.create(
        name="Existing gallery rule",
        ref="archivebox.core.models.Snapshot",
        signal="BEFORE_CAPTURE",
        enabled=False,
        actions=[{"type": "add_tags", "add_tags": "unchanged"}],
    )
    folder_ids = set(Folder.objects.values_list("pk", flat=True))
    rule_ids = set(OutboundWebhook.objects.values_list("pk", flat=True))
    try:
        with homepage_capture_budget(homepage):
            crawl = Crawl.objects.create(urls="\n".join(urls))
            snapshots = [Snapshot.objects.create(crawl=crawl, url=url) for url in urls]
            runner = CrawlRunner(crawl, show_progress=False)
            for snapshot in snapshots:
                snapshot.refresh_from_db()
                expected = 90 if snapshot.url == homepage else 60
                assert snapshot.config.get("CHROME_TIMEOUT", 60) == expected
                payload = asyncio.run(runner.load_snapshot_payload(str(snapshot.pk), prepare=False))
                assert payload["config"]["CHROME_TIMEOUT"] == expected
            if capture_fails:
                raise RuntimeError("Real fixture cleanup on failure")
    except RuntimeError as error:
        assert capture_fails and str(error) == "Real fixture cleanup on failure"
    assert set(Folder.objects.values_list("pk", flat=True)) == folder_ids
    assert set(OutboundWebhook.objects.values_list("pk", flat=True)) == rule_ids
    previous.refresh_from_db()
    assert previous.actions == [{"type": "add_tags", "add_tags": "unchanged"}]
    assert not previous.enabled
    assert set(Snapshot.objects.values_list("url", flat=True)) == set(urls)
    assert not Snapshot.objects.exclude(folder=None).exists()
