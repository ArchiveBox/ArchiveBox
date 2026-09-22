import json

import pytest

from archivebox.core.models import Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    tag = Tag.objects.create(name="api-basic-tag", created_by=api_admin_user)
    crawl = Crawl.objects.create(urls="https://example.com/tag-jsonl-export", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/tag-jsonl-export", crawl=crawl)
    snapshot.tags.add(tag)

    response = client.get(f"/api/v1/core/tag/{tag.id}/snapshots.jsonl", **api_headers)

    assert response.status_code == 200, response.content


def test_tag_snapshots_export_returns_jsonl(client, api_token, tagged_data):
    tag, _ = tagged_data

    response = client.get(
        f"/api/v1/core/tag/{tag.id}/snapshots.jsonl",
        {"api_key": api_token.token},
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/x-ndjson")
    assert f"tag-{tag.slug}-snapshots.jsonl" in response["Content-Disposition"]
    rows = [json.loads(line) for line in response.content.decode().splitlines()]
    rows_by_url = {row["url"]: row for row in rows}
    assert set(rows_by_url) == {"https://example.com/one", "https://example.com/two"}
    assert rows_by_url["https://example.com/one"]["type"] == "Snapshot"
    assert rows_by_url["https://example.com/one"]["title"] == "Example One"
    assert rows_by_url["https://example.com/two"]["type"] == "Snapshot"
    assert rows_by_url["https://example.com/two"]["title"] == "Example Two"
    for row in rows:
        assert "Alpha Research" in row["tags"].split(",")
