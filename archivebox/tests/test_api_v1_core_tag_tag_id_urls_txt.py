import pytest

from archivebox.core.models import Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    tag = Tag.objects.create(name="api-basic-tag", created_by=api_admin_user)
    crawl = Crawl.objects.create(urls="https://example.com/tag-url-export", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/tag-url-export", crawl=crawl)
    snapshot.tags.add(tag)

    response = client.get(f"/api/v1/core/tag/{tag.id}/urls.txt", **api_headers)

    assert response.status_code == 200, response.content


def test_tag_urls_export_returns_plain_text_urls(client, api_token, tagged_data):
    tag, snapshots = tagged_data

    response = client.get(
        f"/api/v1/core/tag/{tag.id}/urls.txt",
        {"api_key": api_token.token},
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert f"tag-{tag.slug}-urls.txt" in response["Content-Disposition"]
    exported_urls = set(filter(None, response.content.decode().splitlines()))
    assert exported_urls == {snapshot.url for snapshot in snapshots}
