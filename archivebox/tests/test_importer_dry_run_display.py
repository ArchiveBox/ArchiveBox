"""Dry Run display uses saved discovery records without creating captures."""

import pytest
from django.test import Client
from django.urls import reverse

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.importers.models import ImporterRun, ImporterSource
from archivebox.importers.service import _finish
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def source_for(user):
    return ImporterSource.objects.create(
        name="Reading list",
        plugin="importer_rss",
        feed="feed",
        created_by=user,
        checkpoint={"cursor": "keep"},
    )


def test_dry_run_initial_and_live_completed_fragment(admin_client, admin_user):
    source = source_for(admin_user)
    run = ImporterRun.objects.create(source=source, action="preview", status="queued")
    counts = (Snapshot.objects.count(), Crawl.objects.count())
    page = admin_client.get(reverse("importers:run", args=[run.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200
    assert b"Dry Run" in page.content and b"Waiting for discovery results." in page.content
    assert b"Items JSON" in page.content
    run.status = "running"
    run.save(update_fields=["status"])
    items = [
        {
            "type": "ImporterItem",
            "id": "one",
            "url": "https://example.org/item?a=1&b=2",
            "title": '<img src=x onerror="alert(1)">',
            "metadata": {"private": "do-not-display"},
        },
    ]
    _finish(run, items, {"status": "succeeded", "account": {}, "checkpoint": {"cursor": "changed"}})
    response = admin_client.get(reverse("importers:run-activity", args=[run.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    data = response.json()
    html = data["html"]
    assert data["active"] is False and data["crawl_id"] is None
    assert "Discovered items · 1" in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "<img src=x" not in html and "do-not-display" not in html
    assert 'href="https://example.org/item?a=1&amp;b=2"' in html
    assert 'rel="noopener noreferrer"' in html
    assert "no captures were created" in html
    source.refresh_from_db()
    run.refresh_from_db()
    assert source.checkpoint == {"cursor": "keep"}
    assert run.action == "preview" and run.to_json()["action"] == "preview"
    assert run.items == items and run.crawl_id is None
    assert (Snapshot.objects.count(), Crawl.objects.count()) == counts
    detail = admin_client.get(source.get_absolute_url(), HTTP_HOST=ADMIN_TEST_HOST)
    assert b">Dry Run</button>" in detail.content
    assert b"/preview/" in detail.content
    assert b">Check access</button>" not in detail.content
    assert b">Run now</button>" in detail.content


def test_dry_run_bounded_safe_items_and_empty_failure_states(admin_client, admin_user):
    source = source_for(admin_user)
    items = [
        {"url": "javascript:alert(1)", "title": "Unsafe scheme"},
        {"url": "https://name:secret@example.org/", "title": "Embedded credentials"},
    ]
    items += [{"url": f"https://example.org/{i}", "title": f"Entry {i}"} for i in range(25)]
    run = ImporterRun.objects.create(source=source, action="preview", status="succeeded", items=items)
    url = reverse("importers:run", args=[run.pk])
    response = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
    html = response.content.decode()
    assert "Discovered items · 27" in html and "Showing the first 20 items" in html
    assert "javascript:alert" not in html and "name:secret" not in html
    assert "Entry 17" in html and "Entry 18" not in html
    assert Client().get(url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    for status, text in [("succeeded", "No items discovered in this Dry Run."), ("failed", "No discovered items were saved.")]:
        run.items = []
        run.status = status
        run.save(update_fields=["items", "status"])
        fragment = admin_client.get(reverse("importers:run-activity", args=[run.pk]), HTTP_HOST=ADMIN_TEST_HOST)
        assert text in fragment.json()["html"]
