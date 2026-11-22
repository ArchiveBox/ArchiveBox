"""Public URL searches paginate without a synchronous full-match count."""

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Folder, Snapshot
from archivebox.tests.conftest import WEB_TEST_HOST

pytestmark = pytest.mark.django_db


@override_settings(PUBLIC_INDEX=True)
@pytest.mark.parametrize("scoped", [False, True])
def test_url_search_uses_lookahead_and_keeps_visibility_and_last_page(client, crawl, settings, scoped):
    settings.CONFIG = settings.CONFIG.model_copy(update={"SNAPSHOTS_PER_PAGE": 10})
    folder = Folder.objects.create(name="URL search scope")
    rows = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://url-page.example/{index}",
                timestamp=str(1900800000 + index),
                crawl=crawl,
                folder=folder if index < 25 else None,
                config={"PERMISSIONS": "public"},
            )
            for index in range(28)
        ],
    )
    for permissions in ("private", "unlisted"):
        Snapshot.objects.create(
            url=f"https://url-page.example/{permissions}",
            crawl=crawl,
            folder=folder,
            config={"PERMISSIONS": permissions},
        )
    params = {"q": "url-page.example", "search_mode": "url"}
    if scoped:
        params["folder"] = str(folder.pk)
    expected = {row.pk for row in (rows[:25] if scoped else rows)}
    found = []
    for page in (1, 2, 3):
        with CaptureQueriesContext(connection) as queries:
            response = client.get("/public/", {**params, "page": page}, HTTP_HOST=WEB_TEST_HOST)
        assert response.status_code == 200
        page_rows = response.context["object_list"]
        assert len(page_rows) == (10 if page < 3 else len(expected) - 20)
        assert response.context["page_obj"].has_next() == (page < 3)
        assert response.context["public_snapshot_count"] == (None if page < 3 else len(expected))
        assert not response.context["public_search_stream_pending"]
        found.extend(row.pk for row in page_rows)
        assert not any("COUNT(" in query["sql"].upper() and "core_snapshot" in query["sql"] for query in queries)
    assert len(found) == len(set(found)) == len(expected)
    assert set(found) == expected
    last = client.get("/public/", {**params, "page": "last"}, HTTP_HOST=WEB_TEST_HOST)
    assert last.status_code == 200
    assert last.context["page_obj"].number == 3
    assert {row.pk for row in last.context["object_list"]} == set(found[20:])
    assert last.context["public_snapshot_count"] == len(expected)
    assert client.get("/public/", {**params, "page": 4}, HTTP_HOST=WEB_TEST_HOST).status_code == 404
    with CaptureQueriesContext(connection) as queries:
        empty = client.get("/public/", {**params, "q": "absent-url.example"}, HTTP_HOST=WEB_TEST_HOST)
    assert empty.status_code == 200
    assert not empty.context["object_list"]
    assert empty.context["public_snapshot_count"] == 0
    assert not any("COUNT(" in query["sql"].upper() and "core_snapshot" in query["sql"] for query in queries)
