import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from .conftest import api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/api-cli-search-basic", created_by=api_admin_user)
    Snapshot.objects.create(url="https://example.com/api-cli-search-basic", crawl=crawl)

    response = api_client_request(
        client,
        "post",
        "/api/v1/cli/search",
        payload={
            "filter_patterns": ["https://example.com/api-cli-search-basic"],
            "filter_type": "exact",
            "as_json": True,
            "as_html": False,
            "as_csv": "",
            "with_headers": False,
        },
        headers=api_headers,
    )

    assert response.status_code == 200, response.content
    assert response.json()["success"] is True
