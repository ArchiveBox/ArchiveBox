import cProfile
import pstats
import re
import time

import pytest
from asgiref.sync import async_to_sync
from django.test import AsyncClient
from django.urls import reverse
from lxml.html import fromstring, tostring

from archivebox.machine.models import Machine
from archivebox.personas.models import Persona
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
        r"admin_render;dur=\d+\.\d, admin_render_cpu;dur=\d+\.\d"
        r"(?:, admin_prepare_runnable;dur=\d+\.\d)?(?:, admin_render_runnable;dur=\d+\.\d)?",
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


def test_settings_form_prepare_and_render_timing(admin_client):
    for path in (
        reverse("add"),
        reverse("admin:personas_persona_change", args=[Persona.get_or_create_default().pk]),
        reverse("admin:machine_machine_change", args=[Machine.current().pk]),
    ):
        plain = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
        measured = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST, HTTP_X_ARCHIVEBOX_ADMIN_TIMING="1")
        assert "Server-Timing" not in plain
        assert_metrics(measured)
        assert measured.status_code == 200
        assert b'id="plugin-settings"' in measured.content


def test_english_admin_render_avoids_global_translation_state(admin_client, snapshot):
    profile = cProfile.Profile()
    response = profile.runcall(admin_client.get, PATH, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert table(response) is not None
    assert b"Snapshots" in response.content
    translation_calls = {
        function: stats[1]
        for (filename, _line, function), stats in pstats.Stats(profile).stats.items()
        if filename.endswith("django/utils/translation/trans_real.py")
        and function in {"get_language", "gettext", "pgettext", "ngettext", "npgettext"}
    }
    # The fixed English UI has no locale selection or translation catalogs.
    # These calls otherwise contend on asgiref.Local's process-wide lock for
    # every reversed URL and translated label during concurrent rendering.
    assert not translation_calls, translation_calls


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


def test_runnable_counter_omits_unknown_and_nonmatching_samples(tmp_path):
    from archivebox.core.admin_timing import _read_schedstat, _runnable_metric

    source = tmp_path / "schedstat"
    assert _read_schedstat(source) is None
    for unavailable in (b"not a counter", b"1 2", b"1 -1 2", b"1 2 3 4", b"1 \xff 2", b"1 18446744073709551616 2"):
        source.write_bytes(unavailable)
        assert _read_schedstat(source) is None

    source.write_text("12345678 0 1\n")
    before = _read_schedstat(source)
    assert before is not None
    assert _runnable_metric("prepare", before, before) is None
    source.write_text("42745678 368130000 67\n")
    after = _read_schedstat(source)
    assert after is not None
    assert _runnable_metric("prepare", before, after) == "admin_prepare_runnable;dur=368.1"
    assert _runnable_metric("render", before, after) == "admin_render_runnable;dur=368.1"
    assert _runnable_metric("render", before, (after[0] + 1, after[1])) is None
    assert _runnable_metric("render", after, before) is None
    assert _runnable_metric("render", None, after) is None
