import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Folder, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import WEB_TEST_HOST

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_folder_data(admin_user, settings):
    settings.CONFIG = settings.CONFIG.model_copy(update={"PUBLIC_INDEX": True, "SNAPSHOTS_PER_PAGE": 2})
    parent = Folder.objects.create(name="Public parent")
    child = Folder.objects.create(name="Public child", parent=parent)
    private = Folder.objects.create(name="Private-only folder", parent=parent)
    unlisted = Folder.objects.create(name="Unlisted-only folder")
    empty = Folder.objects.create(name="Empty folder")
    other = Folder.objects.create(name="Other public folder")
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshots = []
    for name, folder, permission in [
        ("public-one", child, "public"),
        ("public-two", child, "public"),
        ("public-three", child, "public"),
        ("private-one", private, "private"),
        ("unlisted-one", unlisted, "unlisted"),
        ("private-mixed", child, "private"),
        ("unlisted-mixed", child, "unlisted"),
        ("other-public", other, "public"),
    ]:
        snapshots.append(
            Snapshot.objects.create(
                url=f"https://example.com/{name}",
                title=name,
                crawl=crawl,
                folder=folder,
                config={"PERMISSIONS": permission},
            ),
        )
    return parent, child, private, unlisted, empty, other, snapshots


@override_settings(PUBLIC_INDEX=True)
def test_public_sidebar_filters_paths_and_paginated_snapshots(client, public_folder_data):
    parent, child, private, unlisted, empty, other, snapshots = public_folder_data
    response = client.get("/public/", {"folder": parent.pk}, HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    assert [folder.pk for folder in response.context["folder_tree"]] == [other.pk, parent.pk, child.pk]
    assert len(response.context["object_list"]) == 2
    assert all(snapshot.folder_id == child.pk for snapshot in response.context["object_list"])
    html = response.content.decode()
    for forbidden in [
        private.name,
        unlisted.name,
        empty.name,
        "folder-new",
        "folder-edit",
        "folder-drop-target",
        'id="folder-dialog"',
        "private-mixed",
        "unlisted-mixed",
        "other-public",
    ]:
        assert forbidden not in html
    assert f'name="folder" value="{parent.pk}"' in html
    response = client.get("/public/", {"folder": parent.pk, "page": 2}, HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    assert len(response.context["object_list"]) == 1
    assert response.context["object_list"][0].folder_id == child.pk
    assert response.context["public_snapshot_count"] == 3
    response = client.get("/public/", {"folder": child.pk}, HTTP_HOST=WEB_TEST_HOST)
    assert [folder.pk for folder in response.context["folder_breadcrumbs"]] == [parent.pk, child.pk]
    for folder_id in [private.pk, unlisted.pk, empty.pk, "999999999", "invalid"]:
        response = client.get("/public/", {"folder": folder_id}, HTTP_HOST=WEB_TEST_HOST)
        assert response.status_code == 404


def test_public_folder_tree_uses_one_indexed_exists_query(public_folder_data):
    with CaptureQueriesContext(connection) as queries:
        tree = Folder.tree(public=True)
    assert len(queries) == 1
    sql = queries[0]["sql"]
    assert "EXISTS" in sql.upper()
    assert "COUNT(" not in sql.upper()
    assert len(tree) == 3
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN QUERY PLAN " + sql)
            plan = str(cursor.fetchall())
        assert "snapshot_folder_public_idx" in plan


@override_settings(PUBLIC_INDEX=True)
def test_public_folder_visibility_updates_immediately(client, public_folder_data):
    parent, child, _, _, _, _, snapshots = public_folder_data
    assert client.get("/public/", {"folder": child.pk}, HTTP_HOST=WEB_TEST_HOST).status_code == 200
    for snapshot in snapshots[:3]:
        snapshot.config = {"PERMISSIONS": "private"}
        snapshot.save()
    response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
    assert parent.name.encode() not in response.content
    assert child.name.encode() not in response.content
    assert client.get("/public/", {"folder": child.pk}, HTTP_HOST=WEB_TEST_HOST).status_code == 404
