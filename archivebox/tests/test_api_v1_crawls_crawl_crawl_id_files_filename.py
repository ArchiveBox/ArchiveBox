import pytest

from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/crawl-file-root", created_by=api_admin_user)
    crawl.output_dir.mkdir(parents=True, exist_ok=True)
    (crawl.output_dir / "basic.txt").write_text("ok")

    response = client.get(f"/api/v1/crawls/crawl/{crawl.id}/files/basic.txt", **api_headers)

    assert response.status_code == 200, response.content
