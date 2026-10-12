"""User tag edits must survive later saves and filesystem maintenance (#1626)."""

import pytest
from django.urls import reverse

from archivebox.core.models import Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST, api_client_request

pytestmark = pytest.mark.django_db(transaction=True)


def test_creation_tags_are_visible_before_commit_and_do_not_override_edits(api_admin_user):
    from django.db import transaction

    crawl = Crawl.objects.create(urls="https://example.com/atomic-tags", created_by=api_admin_user, tags_str="default")
    with transaction.atomic():
        snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
        assert set(snapshot.tags.values_list("name", flat=True)) == {"default"}
        snapshot.save_tags(["explicit"])
    assert set(snapshot.tags.values_list("name", flat=True)) == {"explicit"}


def test_crawl_tag_edits_only_affect_new_snapshots(api_admin_user):
    crawl = Crawl.objects.create(urls="https://example.com/tags", created_by=api_admin_user, tags_str="original")
    existing = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    assert set(existing.tags.values_list("name", flat=True)) == {"original"}

    crawl.tags_str = "changed"
    crawl.save(update_fields=["tags_str"])
    existing.refresh_from_db()
    existing.save()
    assert set(existing.tags.values_list("name", flat=True)) == {"original"}
    new = Snapshot.objects.create(url="https://example.com/new-tags", crawl=crawl)
    assert set(new.tags.values_list("name", flat=True)) == {"changed"}


@pytest.mark.parametrize("edit", ["replace", "remove", "bulk_remove", "rename", "delete"])
@pytest.mark.parametrize("maintenance", ["save", "reconcile", "rescan"])
def test_tag_edits_survive_maintenance(client, api_admin_user, api_headers, edit, maintenance):
    crawl = Crawl.objects.create(
        urls="https://example.com/tag-maintenance",
        created_by=api_admin_user,
        tags_str="review,keep",
    )
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, status="sealed")
    assert set(snapshot.tags.values_list("name", flat=True)) == {"review", "keep"}
    snapshot.output_dir.mkdir(parents=True, exist_ok=True)
    snapshot.write_index_jsonl()
    index_path = snapshot.output_dir / "index.jsonl"
    original_index = index_path.read_bytes()
    tag = Tag.objects.get(name="review")
    expected = {"keep"}

    if edit == "bulk_remove":
        client.force_login(api_admin_user)
        response = client.post(
            reverse("admin:core_snapshot_changelist"),
            {"action": "remove_tags", "_selected_action": [str(snapshot.pk)], "tags": "review", "index": "0"},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 302
    else:
        method, endpoint, payload = {
            "replace": ("patch", f"/api/v1/core/snapshot/{snapshot.pk}", {"tags": ["keep"]}),
            "remove": ("post", "/api/v1/core/tags/remove-from-snapshot/", {"snapshot_id": str(snapshot.pk), "tag_id": tag.pk}),
            "rename": ("post", f"/api/v1/core/tag/{tag.pk}/rename", {"name": "reviewed"}),
            "delete": ("delete", f"/api/v1/core/tag/{tag.pk}", None),
        }[edit]
        response = api_client_request(client, method, endpoint, payload=payload, headers=api_headers)
        assert response.status_code == 200, response.content
        if edit == "rename":
            expected.add("reviewed")

    assert set(snapshot.tags.values_list("name", flat=True)) == expected
    # Web writes must not synchronously rewrite potentially remote archives.
    assert index_path.read_bytes() == original_index
    if maintenance == "save":
        snapshot.title = "Updated title"
        snapshot.save(update_fields=["title"])
    elif maintenance == "reconcile":
        snapshot.reconcile_with_index()
    else:
        from archivebox.cli.rescan import rescan_snapshots

        rescan_snapshots()
    assert set(snapshot.tags.values_list("name", flat=True)) == expected
    if edit in {"rename", "delete"}:
        assert not Tag.objects.filter(name="review").exists()
