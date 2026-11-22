import json

import pytest

from archivebox.core.models import Snapshot
from archivebox.tests.conftest import API_TEST_HOST


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("format", "card_field", "mime_type", "removed_path"),
    [
        ("txt", "export_urls_url", "text/plain", "urls.txt"),
        ("jsonl", "export_jsonl_url", "application/x-ndjson", "snapshots.jsonl"),
    ],
)
def test_tag_card_exports_reapply_query_and_permissions(client, api_headers, tagged_data, format, card_field, mime_type, removed_path):
    tag, (public, private) = tagged_data
    public.config = {"PERMISSIONS": "public"}
    private.config = {"PERMISSIONS": "private"}
    public.save(update_fields=["config"])
    private.save(update_fields=["config"])
    unlisted = Snapshot.objects.create(
        url="https://example.com/unlisted",
        crawl=public.crawl,
        config={"PERMISSIONS": "unlisted"},
    )
    unlisted.tags.add(tag)
    Snapshot.objects.create(url="https://example.com/other-tag", crawl=public.crawl, config={"PERMISSIONS": "public"})

    search = client.get("/api/v1/core/tags/search/", {"q": tag.name}, **api_headers)
    assert search.status_code == 200
    card = next(card for card in search.json()["tags"] if card["id"] == tag.pk)
    assert card[card_field] == f"/api/v1/core/snapshots/export/{format}?tag={tag.pk}"
    assert client.get(f"/api/v1/core/tag/{tag.pk}/{removed_path}", **api_headers).status_code == 404

    def download(**headers):
        response = client.get(card[card_field], **headers)
        assert response.status_code == 200
        assert response["Content-Type"].startswith(mime_type)
        assert f"snapshots.{format}" in response["Content-Disposition"]
        assert "no-store" in response["Cache-Control"]
        lines = response.getvalue().decode().splitlines()
        if format == "txt":
            return set(lines)
        rows = {row["url"]: row for row in map(json.loads, lines)}
        for row in rows.values():
            assert row["type"] == "Snapshot"
            assert tag.name in row["tags"].split(",")
        if public.url in rows:
            assert rows[public.url]["title"] == "Example One"
        if private.url in rows:
            assert rows[private.url]["title"] == "Example Two"
        return set(rows)

    assert download(**api_headers) == {public.url, private.url, unlisted.url}
    assert download(HTTP_HOST=API_TEST_HOST) == {public.url}
    public.config = {"PERMISSIONS": "private"}
    public.save(update_fields=["config"])
    assert download(HTTP_HOST=API_TEST_HOST) == set()
