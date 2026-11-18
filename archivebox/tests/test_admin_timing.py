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
