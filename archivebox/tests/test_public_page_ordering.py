"""Visibility and stable pagination using the existing chronological indexes."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from archivebox.core.models import Snapshot
from archivebox.tests.conftest import WEB_TEST_HOST

pytestmark = pytest.mark.django_db


@override_settings(PUBLIC_INDEX=True)
@pytest.mark.parametrize("public_count", [0, 12])
def test_public_pages_preserve_timestamp_ties_and_sparse_visibility(client, crawl, settings, public_count):
    settings.CONFIG = settings.CONFIG.model_copy(update={"SNAPSHOTS_PER_PAGE": 5})
    now = timezone.now()
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://hidden-page.example/{index}",
                timestamp=str(1900900000 + index),
                bookmarked_at=now,
                created_at=now,
                crawl=crawl,
                config={"PERMISSIONS": "private" if index % 2 else "unlisted"},
            )
            for index in range(100)
        ],
    )
    public = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://public-page.example/{index}",
                timestamp=str(1900910000 + index),
                bookmarked_at=now - timedelta(days=1),
                created_at=now - timedelta(hours=index % 2),
                crawl=crawl,
                config={"PERMISSIONS": "public"},
            )
            for index in range(public_count)
        ],
    )
    expected = sorted(public, key=lambda row: (-row.bookmarked_at.timestamp(), -row.created_at.timestamp(), row.pk))
    found = []
    pages = max(1, (public_count + 4) // 5)
    for page in range(1, pages + 1):
        with CaptureQueriesContext(connection) as queries:
            response = client.get("/public/", {"page": page}, HTTP_HOST=WEB_TEST_HOST)
        assert response.status_code == 200
        rows = response.context["object_list"]
        assert [row.pk for row in rows] == [row.pk for row in expected[(page - 1) * 5 : page * 5]]
        assert all(row.permissions == "public" for row in rows)
        assert response.context["page_obj"].has_next() == (page < pages)
        assert not any("COUNT(" in query["sql"].upper() and "core_snapshot" in query["sql"] for query in queries)
        found.extend(row.pk for row in rows)
    assert len(found) == len(set(found)) == public_count
    assert response.context["public_snapshot_count"] == public_count
    assert client.get("/public/", {"page": pages + 1}, HTTP_HOST=WEB_TEST_HOST).status_code == 404
