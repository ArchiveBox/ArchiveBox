from urllib.parse import urlencode

import pytest
from asgiref.sync import async_to_sync
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Folder, Snapshot
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("search", ["amazon.com", "not-a-match"])
def test_search_filter_only_does_not_materialize_rows(admin_client, crawl, search):
    folder = Folder.objects.create(name="Search scoped folder")
    wanted = Snapshot.objects.create(url="https://amazon.com/wanted", crawl=crawl, folder=folder)
    Snapshot.objects.create(url="https://amazon.com/outside", crawl=crawl)
    params = {"q": search, "search_mode": "meta", "folder": str(folder.pk)}
    path = "/admin/core/snapshot/"
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get(
            path + "search-stream/",
            {**params, "search_url": path + "?" + urlencode(params)},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
    assert response.status_code == 200
    assert not any("core_archiveresult" in row["sql"].lower() for row in queries)

    async def consume():
        return b"".join([chunk async for chunk in response.streaming_content])

    counts = [int(line.strip()) for line in async_to_sync(consume)().splitlines()]
    assert counts[0] == 0
    assert counts[-1] == (1 if search == "amazon.com" else 0)
    result = admin_client.get(path, params, HTTP_HOST=ADMIN_TEST_HOST)
    assert result.status_code == 200
    assert [row.pk for row in result.context["cl"].result_list] == ([wanted.pk] if search == "amazon.com" else [])
