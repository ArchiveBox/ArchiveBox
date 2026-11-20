"""ArchiveResult admin detail: real forms, persisted summaries and native replay."""

import base64
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.test_archive_storage_isolation import forbid_archive_access

pytestmark = pytest.mark.django_db(transaction=True)

_ONE_PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn8m0sAAAAASUVORK5CYII=")


def make_detail_result(snapshot, *, permissions="public"):
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Machine, Process

    snapshot.permissions = permissions
    snapshot.title = "Result detail fixture"
    snapshot.save()
    plugin_dir = Path(snapshot.output_dir) / "screenshot"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "main.png").write_bytes(_ONE_PIXEL)
    (plugin_dir / "notes.txt").write_text("fixture file")
    process = Process.objects.create(
        machine=Machine.current(),
        cmd=["capture", "argument with spaces"],
        pwd=str(plugin_dir),
        status=Process.StatusChoices.EXITED,
        exit_code=0,
        started_at=timezone.now(),
        stdout="this process log belongs on the process page",
        stderr="stderr-is-not-projected",
    )
    return ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="screenshot",
        hook_name="on_Snapshot__51_screenshot.js",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        process=process,
        output_str="main.png",
        output_size=len(_ONE_PIXEL) + 12,
        output_files={"main.png": {"size": len(_ONE_PIXEL), "mimetype": "image/png"}, "notes.txt": {"size": 12, "mimetype": "text/plain"}},
        output_mimetypes="image/png,text/plain,application/pdf",
    )


def result_detail_url(result):
    return reverse("admin:core_archiveresult_change", args=[result.pk])


def test_archive_result_detail_uses_persisted_metadata_and_native_form(client, admin_user, snapshot):
    from archivebox.config import CONSTANTS

    result = make_detail_result(snapshot)
    client.force_login(admin_user)
    with (
        CaptureQueriesContext(connection) as captured,
        forbid_archive_access(CONSTANTS.ARCHIVE_DIR) as touches,
    ):
        response = client.get(result_detail_url(result), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert not touches
    detail = response.context["result_detail"]
    assert detail["file_count"] == 2 and detail["primary"] == "screenshot/main.png"
    assert detail["primary_size"] and detail["total_size"]
    assert detail["mimes"] == ("image/png", "text/plain") and detail["more_mimes"] == 1
    assert "capture 'argument with spaces'" == detail["command"]
    assert detail["shorthand"].startswith("abx-dl --plugins=screenshot")
    assert urlsplit(detail["files_url"]).path == "/screenshot/"
    assert urlsplit(detail["files_url"]).query == "files=1"
    page = response.content.decode()
    assert page.index("Capture timeline") < page.index('name="output_str"')
    for field in (
        "snapshot",
        "status",
        "start_ts_0",
        "end_ts_0",
        "output_str",
        "output_json",
        "output_files",
        "output_size",
        "output_mimetypes",
    ):
        assert f'name="{field}"' in page
    assert "Exit 0" in page
    assert reverse("admin:machine_process_change", args=[result.process_id]) in page
    assert "this process log belongs on the process page" not in page
    assert all('"machine_process"."stdout"' not in query["sql"] and '"machine_process"."stderr"' not in query["sql"] for query in captured)
    assert all('"crawls_crawl"."urls"' not in query["sql"] for query in captured)
    assert sum('FROM "core_archiveresult"' in query["sql"] for query in captured) == 1

    form = response.context["adminform"].form
    values = {
        key: form[key].value() or "" for key in ("snapshot", "status", "output_json", "output_files", "output_size", "output_mimetypes")
    }
    values.update({"status": "failed", "output_str": "Kept full native edit", "_continue": "Save"})
    invalid = client.post(result_detail_url(result), {**values, "status": "not-a-status"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert invalid.status_code == 200
    assert b'class="result-fields" open' in invalid.content
    saved = client.post(result_detail_url(result), values, HTTP_HOST=ADMIN_TEST_HOST)
    assert saved.status_code == 302
    result.refresh_from_db()
    assert result.status == "failed" and result.output_str == "Kept full native edit"


def test_archive_result_detail_caps_utf8_and_keeps_legacy_raw_data(client, admin_user, snapshot):
    from archivebox.core.models import ArchiveResult

    original = "測🙂" * 10_000 + "tail preserved"
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="title", output_str=original, status="succeeded")
    client.force_login(admin_user)
    response = client.get(result_detail_url(result), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    detail = response.context["result_detail"]
    assert len(detail["output_preview"].encode()) <= 20 * 1024
    assert original.startswith(detail["output_preview"]) and detail["output_truncated"]
    assert detail["total_size"] == "" and detail["file_count"] == 0 and not detail["mimes"]
    assert b"tail preserved" in response.content
    assert b"No file manifest recorded" in response.content

    result.output_files = {"legacy.txt": {"root_relative": True, "size": 0, "mimetype": "text/plain"}}
    result.save(update_fields=["output_files"])
    legacy = client.get(result_detail_url(result), HTTP_HOST=ADMIN_TEST_HOST).context["result_detail"]
    assert legacy["primary"] == "legacy.txt"
    assert legacy["total_size"] and legacy["primary_size"]
    assert urlsplit(legacy["files_url"]).path == "/"


def test_archive_result_detail_does_not_present_a_sample_as_total(client, admin_user, snapshot):
    from archivebox.core.models import ArchiveResult

    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        status="succeeded",
        output_str="asset-00.txt",
        output_files={f"asset-{i:02d}.txt": {"size": i + 1, "mimetype": "text/plain"} for i in range(13)},
    )
    ArchiveResult.objects.filter(pk=result.pk).update(output_size=0, output_mimetypes="")
    client.force_login(admin_user)
    response = client.get(result_detail_url(result), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    detail = response.context["result_detail"]
    assert detail["file_count"] == 13
    assert detail["mimes"] == ("text/plain",)
    assert detail["total_size"] == ""
    assert "asset-12.txt" in response.content.decode()


def configure_detail_browser(live_server, mode):
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    isolated = mode != "single"
    origin = f"http://{'archivebox.localhost' if isolated else 'localhost'}:{port}"
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": origin,
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay" if isolated else "safe-onedomain-nojsreplay",
        "PUBLIC_INDEX": True,
        "PUBLIC_SNAPSHOTS": True,
    }
    machine.save(update_fields=["config"])
    return f"http://admin.archivebox.localhost:{port}" if isolated else origin


def check_native_result_detail(browser, origin, admin_user, result, mode):
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.goto(origin + "/admin/login/")
    page.locator("#id_username").fill(admin_user.username)
    page.locator("#id_password").fill("testpassword")
    page.get_by_role("button", name="Log in", exact=True).click()
    page.goto(origin + result_detail_url(result))
    expect(page.locator(".result-heading .status-badge")).to_have_text("Succeeded")
    expect(page.locator(".result-timeline li")).to_have_count(4)
    expect(page.locator(".result-output-grid > section")).to_have_count(3)
    frames = page.locator(".result-output-grid iframe")
    expect(frames).to_have_count(2)
    for frame in frames.all():
        permissions = frame.get_attribute("sandbox").split()
        assert ("allow-same-origin" in permissions) is (mode != "single")
    expect(page.frame_locator(".result-files-frame").locator(".directory-title")).to_contain_text("screenshot/")
    expect(page.frame_locator(".result-files-frame").get_by_text("main.png", exact=True)).to_be_visible()
    plugin_image = page.frame_locator(".result-frame iframe").locator("img").first
    expect(plugin_image).to_be_visible()
    plugin_image.evaluate("image => image.decode()")
    boxes = [panel.bounding_box() for panel in page.locator(".result-output-grid > section").all()]
    assert len({box["y"] for box in boxes}) == 1 and all(box["width"] >= 300 for box in boxes)
    page.set_viewport_size({"width": 390, "height": 844})
    boxes = [panel.bounding_box() for panel in page.locator(".result-output-grid > section").all()]
    assert [box["y"] for box in boxes] == sorted({box["y"] for box in boxes})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator(".result-files-frame").scroll_into_view_if_needed()
    expect(page.frame_locator(".result-files-frame").get_by_text("main.png", exact=True)).to_be_visible()
    expect(page.locator(".archivebox-toolbar button[name='_continue']")).to_be_visible()
    page.locator(".result-fields > summary").click()
    expect(page.locator('textarea[name="output_str"]')).to_have_value("main.png")
    page.close()


@pytest.mark.parametrize("mode", ["public", "private", "single"])
def test_archive_result_detail_reuses_native_browser_frames(browser_runtime, live_server, admin_user, snapshot, mode):
    origin = configure_detail_browser(live_server, mode)
    result = make_detail_result(snapshot, permissions="private" if mode == "private" else "public")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            check_native_result_detail(browser, origin, admin_user, result, mode)
        finally:
            browser.close()
