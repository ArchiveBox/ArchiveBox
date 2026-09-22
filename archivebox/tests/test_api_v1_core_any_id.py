import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/any", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/any", crawl=crawl)

    response = client.get(f"/api/v1/core/any/{snapshot.id}", follow=True, **api_headers)

    assert response.status_code == 200, response.content
