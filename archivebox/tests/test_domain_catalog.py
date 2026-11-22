from datetime import datetime, timedelta, timezone
from threading import enumerate as active_threads

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.config import CONSTANTS
from archivebox.core.domain_catalog import domain_catalog_page, rebuild_domain_catalog
from archivebox.core.models import Snapshot
from archivebox.personas.models import Persona


@pytest.mark.django_db
def test_small_catalog_uses_current_rows_and_separates_public_witnesses(crawl):
    persona = Persona.objects.create(name="Domain catalog test", created_by=crawl.created_by)
    crawl.persona = persona
    crawl.save(update_fields=["persona"])
    date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    older = Snapshot.objects.create(
        crawl=crawl,
        url="https://docs.example.co.uk/documentation/install/",
        created_at=date,
        output_size=10,
        config={"PERMISSIONS": "public"},
    )
    root = Snapshot.objects.create(
        crawl=crawl,
        url="https://example.co.uk/",
        created_at=date + timedelta(days=1),
        output_size=20,
        config={"PERMISSIONS": "private"},
    )
    Snapshot.objects.create(
        crawl=crawl,
        url="https://tenant.github.io/",
        created_at=date + timedelta(days=2),
        config={"PERMISSIONS": "unlisted"},
    )
    rows, building = domain_catalog_page(ordering="oldest", limit=1)
    assert not building
    assert len(rows) == 1
    row = rows[0]
    assert row["domain"] == "example.co.uk"
    assert row["scope"] == "*.example.co.uk"
    assert row["root_id"] == row["newest_id"] == str(root.pk)
    assert row["public_id"] == row["oldest_id"] == str(older.pk)
    assert row["snapshot_count"] == 2
    assert row["total_size"] == 30
    assert row["persona_count"] == 1
    assert row["oldest_at"] == date
    assert row["newest_at"] == date + timedelta(days=1)
    following, building = domain_catalog_page(ordering="oldest", after=(row["sort_value"], row["domain"]), limit=1)
    assert not building and [item["domain"] for item in following] == ["tenant.github.io"]
    previous, building = domain_catalog_page(
        ordering="oldest",
        after=(following[0]["sort_value"], following[0]["domain"]),
        backwards=True,
        limit=1,
    )
    assert not building and previous == rows
    assert domain_catalog_page(query="AMPLe.CO", public=True)[0][0]["public_id"] == str(older.pk)
    assert domain_catalog_page(query="github.io", public=True) == ([], False)
    older.config = {"PERMISSIONS": "private"}
    older.save(update_fields=["config"])
    assert domain_catalog_page(public=True) == ([], False)
    assert not list(CONSTANTS.CACHE_DIR.glob("domains*"))


@pytest.mark.django_db(transaction=True)
def test_large_catalog_publishes_complete_generation_and_rebuilds_changes(crawl):
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(
                crawl=crawl,
                url=f"https://catalog{number:04}.com/",
                timestamp=str(1930000000 + number),
                config={"PERMISSIONS": "public"},
            )
            for number in range(1001)
        ],
    )
    with CaptureQueriesContext(connection) as queries:
        cold_rows, building = domain_catalog_page(limit=3)
    for worker in active_threads():
        if worker.name == "domain-catalog":
            worker.join(timeout=10)
            assert not worker.is_alive()
    assert cold_rows == [] and building
    assert len(queries) == 1 and "LIMIT 1001" in queries[0]["sql"]
    with CaptureQueriesContext(connection) as queries:
        rows, building = domain_catalog_page(limit=3)
        matching, _ = domain_catalog_page(query="ALOG1000", ordering="domain")
    assert not building
    assert not queries
    assert [row["domain"] for row in rows] == ["catalog0000.com", "catalog0001.com", "catalog0002.com"]
    assert [row["domain"] for row in matching] == ["catalog1000.com"]

    snapshots[-1].url = "https://new-indexed-domain.com/"
    snapshots[-1].save(update_fields=["url"])
    snapshots[-2].delete()
    assert domain_catalog_page(query="catalog1000")[0]
    assert domain_catalog_page(query="catalog0999")[0]
    assert not domain_catalog_page(query="new-indexed-domain")[0]
    assert rebuild_domain_catalog()
    assert domain_catalog_page(query="catalog1000") == ([], False)
    assert domain_catalog_page(query="catalog0999") == ([], False)
    moved, building = domain_catalog_page(query="new-indexed-domain")
    assert not building and len(moved) == 1
    assert moved[0]["root_id"] == moved[0]["public_id"] == str(snapshots[-1].pk)


@pytest.mark.django_db(transaction=True)
def test_failed_catalog_refresh_preserves_previous_generation_and_releases_lock(crawl):
    import os
    from archivebox.core.domain_catalog import _catalog_path, _refresh_lock

    Snapshot.objects.create(crawl=crawl, url="https://retained.example/")
    assert rebuild_domain_catalog()
    path = _catalog_path()
    blocked = path.with_suffix(".building")
    blocked.mkdir()
    os.utime(path, (0, 0))
    rows, building = domain_catalog_page()
    assert not building
    assert [row["domain"] for row in rows] == ["retained.example"]
    for worker in active_threads():
        if worker.name == "domain-catalog":
            worker.join(timeout=10)
            assert not worker.is_alive()
    assert _refresh_lock.acquire(blocking=False)
    _refresh_lock.release()
    blocked.rmdir()
    assert rebuild_domain_catalog()
    assert domain_catalog_page()[0] == rows
