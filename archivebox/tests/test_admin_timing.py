import re
import time

import pytest
from asgiref.sync import async_to_sync
from django.test import AsyncClient
from lxml.html import fromstring, tostring

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)
PATH = "/admin/core/snapshot/"


def table(response):
    nodes = fromstring(response.content).xpath('//table[@id="result_list"]')
    return tostring(nodes[0]) if nodes else None


def assert_metrics(response):
    assert response.status_code == 200
    header = response["Server-Timing"]
    assert re.fullmatch(
        r"admin_prepare;dur=\d+\.\d, admin_prepare_cpu;dur=\d+\.\d, "
        r"admin_render;dur=\d+\.\d, admin_render_cpu;dur=\d+\.\d",
        header,
    )
    return header


def test_admin_timing_sync(admin_client, snapshot):
    plain = admin_client.get(PATH, HTTP_HOST=ADMIN_TEST_HOST)
    measured = admin_client.get(PATH, HTTP_HOST=ADMIN_TEST_HOST, HTTP_X_ARCHIVEBOX_ADMIN_TIMING="1")
    assert "Server-Timing" not in plain
    assert_metrics(measured)
    assert table(plain) == table(measured)
    header = measured["Server-Timing"]
    assert "render" not in measured.__dict__
    time.sleep(0.01)
    assert measured.render() is measured
    assert measured["Server-Timing"] == header
    assert "Server-Timing" not in admin_client.get(PATH, HTTP_HOST=ADMIN_TEST_HOST)


def test_anonymous_and_public_no_admin_metrics(client):
    response = client.get(PATH, HTTP_HOST=ADMIN_TEST_HOST, HTTP_X_ARCHIVEBOX_ADMIN_TIMING="1")
    assert response.status_code == 302
    assert "Server-Timing" not in response
    response = client.get("/public/", HTTP_HOST=ADMIN_TEST_HOST, HTTP_X_ARCHIVEBOX_ADMIN_TIMING="1")
    assert "admin_prepare" not in response.get("Server-Timing", "")


def test_admin_timing_asgi(admin_user, snapshot):
    async def exercise():
        client = AsyncClient()
        await client.aforce_login(admin_user)
        plain = await client.request(method="GET", path=PATH, headers=[(b"host", ADMIN_TEST_HOST.encode())])
        measured = await client.request(
            method="GET",
            path=PATH,
            headers=[(b"host", ADMIN_TEST_HOST.encode()), (b"x-archivebox-admin-timing", b"1")],
        )
        assert "Server-Timing" not in plain
        assert_metrics(measured)
        assert table(plain) == table(measured)
        query = await client.request(method="GET", path=PATH, query_string="_admin_timing=1", headers=[(b"host", ADMIN_TEST_HOST.encode())])
        assert_metrics(query)
        assert table(plain) == table(query)

    async_to_sync(exercise)()


def test_deferred_wait_is_not_render_time(admin_client, snapshot):
    from django.contrib.admin.sites import AdminSite
    from archivebox.core.admin_snapshots import SnapshotAdmin
    from archivebox.core.models import Snapshot

    loaded = admin_client.get(PATH, HTTP_HOST=ADMIN_TEST_HOST, HTTP_X_ARCHIVEBOX_ADMIN_TIMING="1")
    started = time.perf_counter()
    response = SnapshotAdmin(Snapshot, AdminSite()).changelist_view(loaded.wsgi_request)
    assert not response.is_rendered
    time.sleep(0.2)
    response.render()
    header = assert_metrics(response)
    durations = [float(value) for value in re.findall(r"dur=(\d+\.\d)", header)]
    assert durations[0] + durations[2] < (time.perf_counter() - started) * 1000 - 100


def test_nonstaff_no_admin_metrics(client, django_user_model):
    user = django_user_model.objects.create_user(username="nonstaff-timing", password="local-test-only")
    client.force_login(user)
    response = client.get(PATH, HTTP_HOST=ADMIN_TEST_HOST, HTTP_X_ARCHIVEBOX_ADMIN_TIMING="1")
    assert response.status_code == 302
    assert "Server-Timing" not in response


@pytest.mark.parametrize("use_folder", (False, True))
def test_admin_timing_query_preserves_filter_scope_without_leaking_marker(admin_client, snapshot, use_folder):
    from archivebox.core.models import Folder, Snapshot

    filters = {}
    if use_folder:
        folder = Folder.objects.create(name="Timing folder")
        Folder.move_snapshots(Snapshot.objects.filter(pk=snapshot.pk), folder.pk, notify=False)
        Snapshot.objects.create(url="https://outside-folder.example", crawl=snapshot.crawl)
        filters["folder"] = str(folder.pk)

    plain = admin_client.get(PATH, query_params=filters, HTTP_HOST=ADMIN_TEST_HOST)
    measured = admin_client.get(PATH, query_params={**filters, "_admin_timing": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert "Server-Timing" not in plain
    assert_metrics(measured)
    assert table(plain) is not None
    assert table(plain) == table(measured)
    assert "_admin_timing" not in measured.content.decode()
    assert "history.replaceState(history.state" in measured.content.decode()
    if use_folder:
        assert b"outside-folder.example" not in table(measured)
    assert set(measured["Cache-Control"].replace(" ", "").split(",")) >= {"private", "no-store"}
    assert measured.wsgi_request.get_full_path() == plain.wsgi_request.get_full_path()


@pytest.mark.parametrize("is_authenticated", (False, True))
def test_nonstaff_timing_query_never_emits_metrics(client, django_user_model, is_authenticated):
    if is_authenticated:
        client.force_login(django_user_model.objects.create_user(username="nonadmin-query-timing"))
    response = client.get(PATH, query_params={"_admin_timing": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    assert "Server-Timing" not in response
