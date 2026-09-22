from datetime import datetime, timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from archivebox.core.models import Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import api_client_request, init_archive


pytestmark = pytest.mark.django_db(transaction=True)


def _crawl(user, urls: str, label: str) -> Crawl:
    return Crawl.objects.create(
        urls=urls,
        created_by=user,
        status=Crawl.StatusChoices.SEALED,
        retry_at=None,
        tags_str=label,
    )


def _snapshot(crawl: Crawl, url: str, *, status: str = Snapshot.StatusChoices.SEALED, tag: str = "", bookmarked_at=None) -> Snapshot:
    snapshot = Snapshot.objects.create(
        url=url,
        crawl=crawl,
        status=status,
        retry_at=None,
        bookmarked_at=bookmarked_at or timezone.now(),
    )
    if tag:
        tag_obj, _ = Tag.objects.get_or_create(name=tag)
        snapshot.tags.add(tag_obj)
    return snapshot


def _touch_output(snapshot: Snapshot) -> Path:
    output_dir = Path(snapshot.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "api-remove-test.txt").write_text(str(snapshot.id))
    return output_dir


def _bulk_timeout_snapshots(crawl: Crawl, *, count: int = 3) -> tuple[list[Snapshot], dict[str, Path]]:
    base = timezone.make_aware(datetime(2026, 2, 1, 12, 0, 0))
    snapshots = [
        Snapshot(
            url=f"https://example.com/remove-timeout-{idx}",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
            timestamp=f"88{idx:030d}",
            bookmarked_at=base + timedelta(seconds=idx),
            created_at=base + timedelta(seconds=idx),
        )
        for idx in range(count)
    ]
    Snapshot.objects.bulk_create(snapshots, batch_size=1000)

    return snapshots, {str(snapshot.id): _touch_output(snapshot) for snapshot in snapshots}


def _post_remove(client, api_headers, body: dict):
    return api_client_request(
        client,
        "post",
        "/api/v1/cli/remove",
        payload=body,
        headers=api_headers,
    )


def test_cli_remove_api_removes_rows_and_respects_snapshot_filters(client, tmp_path, api_admin_user, api_headers):
    init_archive(tmp_path)
    base = timezone.make_aware(datetime(2026, 1, 1, 12, 0, 0))

    crawl_a = _crawl(api_admin_user, "https://alpha.example.com/articles/needle", "crawl-a")
    crawl_b = _crawl(api_admin_user, "https://beta.example.org/posts/needle", "crawl-b")
    exact = _snapshot(crawl_a, "https://alpha.example.com/articles/exact", tag="api-keep", bookmarked_at=base)
    keep = _snapshot(crawl_a, "https://alpha.example.com/articles/needle", tag="api-keep", bookmarked_at=base + timedelta(hours=1))
    wrong_status = _snapshot(
        crawl_a,
        "https://alpha.example.com/articles/needle-queued",
        status=Snapshot.StatusChoices.QUEUED,
        tag="api-keep",
        bookmarked_at=base + timedelta(hours=2),
    )
    other_crawl = _snapshot(crawl_b, "https://beta.example.org/posts/needle", tag="api-other", bookmarked_at=base + timedelta(hours=3))
    exact_dir = _touch_output(exact)
    keep_dir = _touch_output(keep)
    wrong_status_dir = _touch_output(wrong_status)
    other_crawl_dir = _touch_output(other_crawl)

    exact_response = _post_remove(
        client,
        api_headers,
        {
            "filter_type": "exact",
            "filter_patterns": [exact.url],
            "timeout": 60,
        },
    )
    assert exact_response.status_code == 200, exact_response.content
    exact_payload = exact_response.json()
    assert exact_payload["success"] is True
    assert exact_payload["result"]["removed_count"] == 1
    assert exact_payload["result"]["removed_snapshot_ids"] == [str(exact.id)]
    assert exact_payload["result"]["not_removed_count"] == 0
    assert not Snapshot.objects.filter(pk=exact.pk).exists()
    assert not exact_dir.exists()

    filtered_response = _post_remove(
        client,
        api_headers,
        {
            "filter_type": "substring",
            "filter_patterns": ["needle"],
            "status": Snapshot.StatusChoices.SEALED,
            "tag": "api-keep",
            "url__istartswith": "https://alpha.example.com",
            "crawl_id": str(crawl_a.id),
            "after": (base + timedelta(minutes=30)).timestamp(),
            "before": (base + timedelta(hours=2)).timestamp(),
            "timeout": 60,
        },
    )
    assert filtered_response.status_code == 200, filtered_response.content
    filtered_payload = filtered_response.json()
    assert filtered_payload["success"] is True
    assert filtered_payload["result"]["removed_count"] == 1
    assert filtered_payload["result"]["removed_snapshot_ids"] == [str(keep.id)]
    assert filtered_payload["result"]["not_removed_count"] == 0
    assert not Snapshot.objects.filter(pk=keep.pk).exists()
    assert not keep_dir.exists()
    assert Snapshot.objects.filter(pk=wrong_status.pk).exists()
    assert Snapshot.objects.filter(pk=other_crawl.pk).exists()
    assert wrong_status_dir.exists()
    assert other_crawl_dir.exists()


def test_cli_remove_api_reports_timeout_and_clamps_timeout_to_sixty_seconds(client, tmp_path, api_admin_user, api_headers):
    init_archive(tmp_path)
    crawl = _crawl(api_admin_user, "https://example.com/remove-timeout-0", "timeout")
    snapshots, output_dirs_by_id = _bulk_timeout_snapshots(crawl)

    timeout_response = _post_remove(
        client,
        api_headers,
        {
            "filter_type": "substring",
            "filter_patterns": ["remove-timeout-"],
            "timeout": 0,
        },
    )
    assert timeout_response.status_code == 200, timeout_response.content
    timeout_payload = timeout_response.json()
    assert timeout_payload["success"] is False
    assert timeout_payload["errors"]
    assert set(timeout_payload["result"]) == {
        "removed_count",
        "removed_snapshot_ids",
        "not_removed_count",
        "not_removed_snapshot_ids",
        "success",
        "error",
        "timeout",
    }
    assert timeout_payload["result"]["success"] is False
    assert timeout_payload["result"]["timeout"] == 0.0
    assert timeout_payload["result"]["error"]
    assert timeout_payload["result"]["removed_count"] == len(timeout_payload["result"]["removed_snapshot_ids"])
    assert timeout_payload["result"]["not_removed_count"] == len(timeout_payload["result"]["not_removed_snapshot_ids"])
    assert timeout_payload["result"]["removed_count"] == 0
    assert timeout_payload["result"]["not_removed_count"] == len(snapshots)
    assert timeout_payload["result"]["removed_count"] + timeout_payload["result"]["not_removed_count"] == len(snapshots)

    removed_ids = set(timeout_payload["result"]["removed_snapshot_ids"])
    not_removed_ids = set(timeout_payload["result"]["not_removed_snapshot_ids"])
    assert Snapshot.objects.filter(url__icontains="remove-timeout-").count() == len(not_removed_ids)
    assert removed_ids == set()
    assert not_removed_ids == set(output_dirs_by_id)
    for snapshot_id in not_removed_ids:
        assert Snapshot.objects.filter(pk=snapshot_id).exists()
        assert output_dirs_by_id[snapshot_id].exists()

    clamp_snapshot = _snapshot(crawl, "https://example.com/remove-timeout-clamp")
    clamp_dir = _touch_output(clamp_snapshot)
    clamp_response = _post_remove(
        client,
        api_headers,
        {
            "filter_type": "exact",
            "filter_patterns": [clamp_snapshot.url],
            "timeout": 999,
        },
    )
    assert clamp_response.status_code == 200, clamp_response.content
    clamp_payload = clamp_response.json()
    assert clamp_payload["success"] is True
    assert clamp_payload["result"]["timeout"] == 60.0
    assert clamp_payload["result"]["removed_snapshot_ids"] == [str(clamp_snapshot.id)]
    assert not Snapshot.objects.filter(pk=clamp_snapshot.pk).exists()
    assert not clamp_dir.exists()
