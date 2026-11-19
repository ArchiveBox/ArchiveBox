import pytest
from django.template.loader import render_to_string

from archivebox.core.models import Folder, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db
HOST = {"HTTP_HOST": ADMIN_TEST_HOST}
URL = "/admin/core/folder/remove/"


def state(client, folder):
    return client.get(
        URL,
        {"folder_id": str(folder.pk), "intent": "empty_only", "q": "not-a-match", "status": "sealed", "limit": 0},
        **HOST,
    )


@pytest.mark.parametrize("status", ["queued", "started", "sealed", Snapshot.DELETING_STATE])
def test_folder_removal_counts_all_persisted_statuses(admin_client, admin_user, status):
    folder = Folder.objects.create(name="Keep contents")
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, folder=folder, status=status)
    assert state(admin_client, folder).json()["has_snapshots"] is True
    response = admin_client.post(URL, {"folder_id": str(folder.pk), "intent": "empty_only"}, **HOST)
    assert response.status_code == 409
    snapshot.refresh_from_db()
    assert snapshot.folder_id == folder.pk
    assert snapshot.status == status
    # The old edit dialog cannot bypass the same gate by omitting intent.
    assert admin_client.post(URL, {"folder_id": str(folder.pk)}, **HOST).status_code == 409


def test_folder_removal_rechecks_after_empty_preview(admin_client, admin_user):
    folder = Folder.objects.create(name="New arrival")
    assert state(admin_client, folder).json()["has_snapshots"] is False
    crawl = Crawl.objects.create(urls="https://example.com/new", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, folder=folder)
    assert admin_client.post(URL, {"folder_id": str(folder.pk), "intent": "empty_only"}, **HOST).status_code == 409
    Folder.move_snapshots(Snapshot.objects.filter(pk=snapshot.pk), None)
    assert admin_client.post(URL, {"folder_id": str(folder.pk), "intent": "empty_only"}, **HOST).json() == {"deleted": True}
    assert not Folder.objects.filter(pk=folder.pk).exists()
    assert Snapshot.objects.filter(pk=snapshot.pk).exists()


def test_folder_removal_never_lifts_children(admin_client):
    parent = Folder.objects.create(name="Parent")
    child = Folder.objects.create(name="Child", parent=parent)
    response = state(admin_client, parent)
    assert response.json()["has_children"] is True
    assert response.json()["has_snapshots"] is False
    assert admin_client.post(URL, {"folder_id": str(parent.pk), "intent": "empty_only"}, **HOST).status_code == 409
    child.refresh_from_db()
    assert child.parent_id == parent.pk


def test_smart_folder_checks_matches_not_current_list(admin_client, admin_user):
    folder = Folder.objects.create(
        name="Smart",
        rules={"op": "AND", "rules": [{"field": "url", "lookup": "icontains", "value": "example.com"}], "limit": 1},
    )
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, status=Snapshot.DELETING_STATE)
    assert state(admin_client, folder).json()["has_snapshots"] is True
    assert admin_client.post(URL, {"folder_id": str(folder.pk), "intent": "empty_only"}, **HOST).status_code == 409
    assert Snapshot.objects.filter(pk=snapshot.pk).exists()
    assert folder.snapshots.count() == 0


def test_folder_menu_waits_for_authoritative_action(admin_client, admin_user):
    from django.contrib.auth.context_processors import PermWrapper

    folder = Folder.objects.create(name="Empty")
    html = render_to_string("core/folder_tree.html", {"folder_tree": Folder.tree(), "perms": PermWrapper(admin_user)})
    assert "Checking folder…" in html
    assert 'aria-disabled="true"' in html
    assert f'data-delete-snapshots-url="/admin/core/snapshot/?folder={folder.pk}#delete-snapshots"' in html
    assert f'href="/admin/core/snapshot/?folder={folder.pk}#delete-snapshots"' not in html
    assert state(admin_client, folder).json() == {"has_snapshots": False, "has_children": False, "can_delete": True}


def test_folder_native_delete_queues_only_scope_and_still_blocks_removal(admin_client, admin_user):
    folder = Folder.objects.create(name="Queue then remove")
    other = Folder.objects.create(name="Unrelated")
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    inside = Snapshot.objects.create(url=crawl.urls, crawl=crawl, folder=folder)
    outside = Snapshot.objects.create(url="https://example.org/", crawl=crawl, folder=other)
    endpoint = f"/admin/core/snapshot/?folder={folder.pk}"
    data = {"action": "delete_selected", "select_across": "1", "_selected_action": [str(inside.pk)], "index": "0"}
    preview = admin_client.post(endpoint, data, **HOST)
    assert preview.status_code == 200
    assert preview.context["count"] == 1
    response = admin_client.post(endpoint, {**data, "post": "yes", "selection": preview.context["selection"]}, **HOST)
    assert response.status_code == 302
    inside.refresh_from_db()
    outside.refresh_from_db()
    assert inside.status == Snapshot.DELETING_STATE
    assert inside.folder_id == folder.pk
    assert outside.status == "queued"
    assert state(admin_client, folder).json()["has_snapshots"] is True
    assert admin_client.post(URL, {"folder_id": str(folder.pk), "intent": "empty_only"}, **HOST).status_code == 409


def test_empty_folder_removal_requires_delete_permission(client, django_user_model):
    from django.contrib.auth.models import Permission

    user = django_user_model.objects.create_user(username="folder-reader", password="fixture-only", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="view_folder"))
    client.force_login(user)
    folder = Folder.objects.create(name="Protected")
    assert state(client, folder).json()["can_delete"] is False
    assert client.post(URL, {"folder_id": str(folder.pk), "intent": "empty_only"}, **HOST).status_code == 403
    assert Folder.objects.filter(pk=folder.pk).exists()


@pytest.mark.parametrize(
    ("permissions", "get_status", "can_delete", "post_status"),
    [
        (["view_snapshot", "delete_snapshot"], 200, False, 403),
        (["view_snapshot"], 403, None, 403),
        (["delete_snapshot"], 403, None, 403),
        ([], 403, None, 403),
        (["delete_folder"], 200, True, 200),
    ],
)
def test_folder_state_preserves_snapshot_delete_authority(client, django_user_model, permissions, get_status, can_delete, post_status):
    from django.contrib.auth.models import Permission
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    user = django_user_model.objects.create_user(username="scoped-folder-action", password="fixture-only", is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=permissions))
    client.force_login(user)
    folder = Folder.objects.create(name="Scoped permissions")
    with CaptureQueriesContext(connection) as queries:
        response = state(client, folder)
    assert response.status_code == get_status
    assert not any("FOR UPDATE" in query["sql"].upper() or query["sql"].upper().startswith("BEGIN") for query in queries)
    if get_status == 200:
        assert response.json()["can_delete"] is can_delete
    if permissions == ["view_snapshot", "delete_snapshot"]:
        page = client.get("/admin/core/snapshot/", **HOST)
        assert page.status_code == 200
        assert f'data-delete-snapshots-url="/admin/core/snapshot/?folder={folder.pk}#delete-snapshots"'.encode() in page.content
    response = client.post(URL, {"folder_id": str(folder.pk), "intent": "empty_only"}, **HOST)
    assert response.status_code == post_status
    assert Folder.objects.filter(pk=folder.pk).exists() is (post_status != 200)
