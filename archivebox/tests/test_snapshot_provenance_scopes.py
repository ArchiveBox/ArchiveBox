"""The library's provenance filters share one membership across routes."""

import csv
import io
from urllib.parse import urlencode

import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse

from archivebox.core.models import Folder, Snapshot, Tag
from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.importers.models import ImporterRun, ImporterSource
from archivebox.personas.models import Persona
from archivebox.tests.conftest import ADMIN_TEST_HOST, API_TEST_HOST
from archivebox.tests.test_snapshot_exports import exported_ids

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def provenance_data(admin_user):
    persona = Persona.objects.create(name="Research profile")
    other_persona = Persona.objects.create(name="Personal profile")
    template = Crawl.objects.create(urls="https://example.org/", persona=persona, created_by=admin_user)
    schedule = CrawlSchedule.objects.create(template=template, schedule="@daily", created_by=admin_user)
    child = schedule.enqueue()
    imported = Crawl.objects.create(urls="https://example.org/", persona=persona, created_by=admin_user, label="Daily links")
    unrelated = Crawl.objects.create(urls="https://example.org/", persona=other_persona, created_by=admin_user, label=imported.label)
    importer = ImporterSource.objects.create(
        name=imported.label,
        plugin="importer_rss",
        feed="rss",
        persona=other_persona,
        created_by=admin_user,
    )
    for _ in range(2):
        ImporterRun.objects.create(source=importer, crawl=imported, status=ImporterRun.Status.SUCCEEDED)
    ImporterRun.objects.create(source=importer, status=ImporterRun.Status.SUCCEEDED, action=ImporterRun.Action.PREVIEW)
    folder = Folder.objects.create(name="Research")
    tag = Tag.objects.create(name="Reading")
    snapshots = [
        Snapshot.objects.create(
            crawl=crawl,
            url=f"https://example.org/{i}",
            title=f"Reading {i}",
            folder=folder if i != 2 else None,
            config={"PERMISSIONS": "public"},
        )
        for i, crawl in enumerate((template, child, imported, unrelated))
    ]
    for snapshot in snapshots[:3]:
        snapshot.tags.add(tag)
    return {
        "persona": persona,
        "importer": importer,
        "crawl_schedule": schedule,
        "crawl": child,
        "folder": folder,
        "tag": tag,
    }, snapshots


def test_admin_provenance_scopes_in_list_grid_and_exports(admin_client, provenance_data):
    scopes, snapshots = provenance_data
    path = reverse("admin:core_snapshot_changelist")
    for selected, expected in (
        (("persona",), (0, 1, 2)),
        (("importer",), (2,)),
        (("crawl_schedule",), (0, 1)),
        (("crawl",), (1,)),
        (("persona", "importer", "tag"), (2,)),
        (("crawl_schedule", "crawl", "folder", "tag"), (1,)),
        (("crawl_schedule", "importer"), ()),
    ):
        params = {key: str(scopes[key].pk) for key in selected}
        ids = [snapshots[i].pk for i in reversed(expected)]
        for route in (path, reverse("admin:grid")):
            response = admin_client.get(route, params, HTTP_HOST=ADMIN_TEST_HOST)
            assert response.status_code == 200, (selected, response.status_code)
            assert [row.pk for row in response.context["cl"].result_list] == ids
        exported = admin_client.get(path + "export.csv", params, HTTP_HOST=ADMIN_TEST_HOST)
        assert exported.status_code == 200
        assert exported_ids(exported, "csv") == {str(pk) for pk in ids}


def test_admin_provenance_scope_follows_sorted_search_stream(admin_client, provenance_data):
    scopes, snapshots = provenance_data
    path = reverse("admin:core_snapshot_changelist")
    params = {"persona": str(scopes["persona"].pk), "q": "title:reading", "o": "2"}
    search_url = path + "?" + urlencode(params)
    stream = admin_client.get(
        path + "search-stream/",
        {**params, "search_url": search_url},
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_X_ARCHIVEBOX_SEARCH_PAGE="first",
    )
    assert stream.status_code == 200

    async def consume():
        return b"".join([chunk async for chunk in stream.streaming_content])

    counts = [int(line) for line in async_to_sync(consume)().splitlines() if line.strip().isdigit()]
    assert counts[-1] == 3
    response = admin_client.get(
        path,
        params,
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_X_ARCHIVEBOX_SEARCH_GENERATION=stream["X-ArchiveBox-Search-Generation"],
        HTTP_X_ARCHIVEBOX_SEARCH_PAGE=stream["X-ArchiveBox-Search-Page"],
    )
    assert response.status_code == 200
    assert [row.pk for row in response.context["cl"].result_list] == [row.pk for row in snapshots[:3]]
    export_url = response.context["list_export_urls"]["csv"]
    download = admin_client.get(export_url, HTTP_HOST=ADMIN_TEST_HOST)
    assert download.status_code == 200
    csv_rows = csv.DictReader(io.StringIO(download.getvalue().decode()))
    assert [row["id"] for row in csv_rows] == [str(row.pk) for row in snapshots[:3]]


def test_invalid_provenance_filter_selects_nothing(admin_client, provenance_data):
    path = reverse("admin:core_snapshot_changelist")
    for key in ("persona", "importer", "crawl_schedule", "crawl"):
        response = admin_client.get(path, {key: "not-an-id"}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert list(response.context["cl"].result_list) == []
        exported = admin_client.get(path + "export.csv", {key: "not-an-id"}, HTTP_HOST=ADMIN_TEST_HOST)
        assert exported.status_code == 200
        assert exported_ids(exported, "csv") == set()


def test_provenance_scopes_do_not_expand_anonymous_export(client, provenance_data):
    scopes, _snapshots = provenance_data
    for key in ("persona", "importer", "crawl_schedule", "crawl"):
        response = client.get("/api/v1/core/snapshots/export/csv", {key: str(scopes[key].pk)}, HTTP_HOST=API_TEST_HOST)
        assert response.status_code == 400


def test_provenance_scopes_require_native_permissions(client, django_user_model, provenance_data):
    from django.contrib.auth.models import Permission
    from django.core.exceptions import PermissionDenied

    from archivebox.core.exports import get_export_queryset

    scopes, _snapshots = provenance_data
    staff = django_user_model.objects.create_user(username="snapshot-viewer", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_snapshot"))
    client.force_login(staff)
    path = reverse("admin:core_snapshot_changelist")
    assert client.get(path, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
    for key in ("persona", "importer", "crawl_schedule", "crawl"):
        params = {key: str(scopes[key].pk)}
        for route in (path, reverse("admin:grid"), path + "export.csv"):
            assert client.get(route, params, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
        search_params = {**params, "q": "title:reading"}
        assert (
            client.get(
                path + "search-stream/",
                {**search_params, "search_url": path + "?" + urlencode(search_params)},
                HTTP_HOST=ADMIN_TEST_HOST,
                HTTP_X_ARCHIVEBOX_SEARCH_PAGE="first",
            ).status_code
            == 403
        )
        with pytest.raises(PermissionDenied):
            get_export_queryset(params, user=staff, public_only=False)
        assert get_export_queryset(params, public_only=False).exists()

    staff.user_permissions.add(
        Permission.objects.get(content_type__app_label="personas", codename="view_persona"),
        Permission.objects.get(content_type__app_label="crawls", codename="change_crawl"),
        Permission.objects.get(content_type__app_label="crawls", codename="view_crawlschedule"),
    )
    for key in ("persona", "crawl_schedule", "crawl"):
        assert client.get(path, {key: str(scopes[key].pk)}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
    assert client.get(path, {"importer": str(scopes["importer"].pk)}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
