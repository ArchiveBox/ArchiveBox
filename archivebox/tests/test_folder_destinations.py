"""Folder destinations through native add APIs, recursive queues, and schedules."""

import pytest

from archivebox.core.models import Folder, Snapshot
from archivebox.uuid_compat import uuid7
from archivebox.crawls.models import Crawl, CrawlSchedule

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("endpoint", ["/api/v1/cli/add", "/api/v1/crawls/crawls", "/api/v1/core/snapshots"])
def test_add_api_folder_destination(client, api_headers, endpoint):
    folder = Folder.objects.create(name="Reading")
    payload = {"folder_id": folder.pk}
    payload["url" if endpoint.endswith("snapshots") else "urls"] = (
        "https://example.com/folder-seed" if endpoint.endswith("snapshots") else ["https://example.com/folder-seed"]
    )
    response = client.post(endpoint, data=payload, content_type="application/json", **api_headers)
    assert response.status_code == 200, response.content
    crawl = Crawl.objects.latest("created_at")
    assert crawl.folder_id == folder.pk
    snapshot = crawl.snapshot_set.first() or crawl.create_snapshots_from_urls()[0]
    assert snapshot.folder_id == folder.pk
    if endpoint.endswith("snapshots"):
        assert response.json()["folder_id"] == str(folder.pk)
    if endpoint.endswith("crawls"):
        assert response.json()["folder_id"] == str(folder.pk)


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/api/v1/cli/add", {"urls": ["https://example.com/rejected"]}),
        ("/api/v1/crawls/crawls", {"urls": ["https://example.com/rejected"]}),
        ("/api/v1/core/snapshots", {"url": "https://example.com/rejected"}),
        ("/api/v1/cli/schedule", {"every": "daily", "import_path": "https://example.com/rejected"}),
    ],
)
def test_missing_destination_rejected_before_any_crawl(client, api_headers, endpoint, payload):
    response = client.post(endpoint, data={**payload, "folder_id": str(uuid7())}, content_type="application/json", **api_headers)
    assert response.status_code == 404, response.content
    assert not Crawl.objects.exists()
    assert not CrawlSchedule.objects.exists()
    assert not Snapshot.objects.exists()


def test_schedule_folder_inheritance_and_deletion(client, api_headers):
    folder = Folder.objects.create(name="Scheduled reading")
    response = client.post(
        "/api/v1/cli/schedule",
        data={"every": "daily", "import_path": "https://example.com/scheduled", "depth": 1, "folder_id": folder.pk, "quiet": True},
        content_type="application/json",
        **api_headers,
    )
    assert response.status_code == 200, response.content
    scheduled = CrawlSchedule.objects.get(pk=response.json()["result"]["created_schedule_ids"][0])
    assert scheduled.template.folder_id == folder.pk
    for _ in range(2):
        crawl = scheduled.enqueue()
        assert crawl.folder_id == folder.pk
        seed = crawl.create_snapshots_from_urls()[0]
        assert seed.folder_id == folder.pk
    child = crawl.create_discovered_snapshot(seed, url="https://example.com/scheduled/child", depth=1)
    assert child.folder_id == folder.pk
    assert crawl.create_discovered_snapshot(seed, url=child.url, depth=1) is None
    folder.delete()
    crawl.refresh_from_db()
    seed.refresh_from_db()
    child.refresh_from_db()
    assert crawl.folder_id is seed.folder_id is child.folder_id is None
    assert scheduled.enqueue().folder_id is None


def test_destination_never_moves_existing_captures(client, api_headers, api_admin_user):
    original = Folder.objects.create(name="Original")
    destination = Folder.objects.create(name="New captures")
    old_crawl = Crawl.objects.create(urls="https://example.com/already-saved", created_by=api_admin_user)
    old = Snapshot.objects.create(url=old_crawl.urls, crawl=old_crawl, folder=original)
    response = client.post(
        "/api/v1/crawls/crawls",
        data={"urls": [old.url], "folder_id": destination.pk, "config": {"ONLY_NEW": True}},
        content_type="application/json",
        **api_headers,
    )
    assert response.status_code == 200, response.content
    crawl = Crawl.objects.get(pk=response.json()["id"])
    assert crawl.create_snapshots_from_urls() == []
    response = client.post(
        "/api/v1/core/snapshots",
        data={"url": old.url, "crawl_id": str(crawl.pk), "folder_id": destination.pk},
        content_type="application/json",
        **api_headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["id"] == str(old.pk)
    old.refresh_from_db()
    assert old.folder_id == original.pk
    crawl.config["ONLY_NEW"] = False
    crawl.save()
    replacement = crawl.create_snapshots_from_urls()[0]
    assert replacement.folder_id == destination.pk
    replacement.folder = None
    replacement.save()
    replacement.refresh_from_db()
    assert replacement.folder_id is None
    assert old.folder_id == original.pk


def test_explicit_snapshot_destination_preserves_crawl_default(client, api_headers, api_admin_user):
    default = Folder.objects.create(name="Crawl default")
    explicit = Folder.objects.create(name="Explicit capture")
    crawl = Crawl.objects.create(urls="https://example.com/default", folder=default, created_by=api_admin_user)
    response = client.post(
        "/api/v1/core/snapshots",
        data={"url": "https://example.com/explicit", "crawl_id": str(crawl.pk), "folder_id": explicit.pk},
        content_type="application/json",
        **api_headers,
    )
    assert response.status_code == 200, response.content
    assert Snapshot.objects.get(pk=response.json()["id"]).folder_id == explicit.pk
    crawl.refresh_from_db()
    assert crawl.folder_id == default.pk
    assert crawl.create_snapshots_from_urls()[0].folder_id == default.pk


def test_deleted_folder_does_not_break_active_crawl(api_admin_user):
    folder = Folder.objects.create(name="Temporary destination")
    crawl = Crawl.objects.create(urls="https://example.com/active", folder=folder, created_by=api_admin_user)
    folder.delete()
    # The runner can retain this crawl instance while an admin deletes its folder.
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    assert snapshot.folder_id is None


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/api/v1/cli/add", {"urls": ["https://example.com/denied"]}),
        ("/api/v1/crawls/crawls", {"urls": ["https://example.com/denied"]}),
        ("/api/v1/core/snapshots", {"url": "https://example.com/denied"}),
        ("/api/v1/cli/schedule", {"every": "daily", "import_path": "https://example.com/denied"}),
    ],
)
def test_folder_add_apis_retain_superuser_permission(client, django_user_model, endpoint, payload):
    from archivebox.api.models import APIToken
    from archivebox.tests.conftest import api_auth_headers

    user = django_user_model.objects.create_user(username="folder-reader", is_staff=True)
    token = APIToken.objects.create(created_by=user)
    folder = Folder.objects.create(name="Protected destination")
    response = client.post(
        endpoint,
        data={**payload, "folder_id": folder.pk},
        content_type="application/json",
        **api_auth_headers(token.token, django_client=True),
    )
    assert response.status_code == 403, response.content
    assert not Crawl.objects.exists()
    assert not Snapshot.objects.exists()
