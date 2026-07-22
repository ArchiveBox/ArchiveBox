import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_snapshots_api_filters_status_column(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by=api_admin_user,
        status=Crawl.StatusChoices.SEALED,
        retry_at=None,
    )
    Snapshot.objects.create(
        url="https://example.com/api-status-queued",
        crawl=crawl,
        status=Snapshot.StatusChoices.QUEUED,
    )
    sealed_snapshot = Snapshot.objects.create(
        url="https://example.com/api-status-sealed",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        retry_at=None,
    )

    response = client.get(
        "/api/v1/core/snapshots",
        {"status": "sealed"},
        **api_headers,
    )
    assert response.status_code == 200, response.content
    payload = response.json()
    items = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
    assert [item["id"] for item in items] == [str(sealed_snapshot.id)]
    assert [item["status"] for item in items] == ["sealed"]
