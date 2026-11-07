"""Configured public aliases work without admitting unrelated public hosts."""

import pytest

from archivebox.machine.models import Machine
from archivebox.tests.test_snapshot_output_stacks import save_output

pytestmark = pytest.mark.django_db


def configure_hosts(mode="safe-subdomains-fullreplay", allowed="demo.archivebox.localhost,archive.example.test"):
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": "http://archivebox.localhost:5797",
        "SERVER_SECURITY_MODE": mode,
        "ALLOWED_HOSTS": allowed,
        "PUBLIC_INDEX": True,
    }
    machine.save(update_fields=["config"])


@pytest.mark.parametrize("host", ["demo.archivebox.localhost", "archive.example.test", "web.archivebox.localhost"])
@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "auto"])
def test_allowed_public_alias_serves_index(client, host, mode):
    configure_hosts(mode=mode)
    response = client.get("/public/", HTTP_HOST=f"{host}:5797")
    assert response.status_code == 200
    assert b"ArchiveBox" in response.content


@pytest.mark.parametrize(
    "mode",
    ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay", "unsafe-onedomain-noadmin", "danger-onedomain-fullreplay", "auto"],
)
@pytest.mark.parametrize("host", ["unrelated.example.test", "archive.example.test.attacker.test"])
def test_unconfigured_public_host_is_rejected(client, mode, host):
    configure_hosts(mode=mode)
    response = client.get("/public/", HTTP_HOST=f"{host}:5797")
    assert response.status_code == 400
    assert "Location" not in response


@pytest.mark.parametrize("mode", ["safe-onedomain-nojsreplay", "unsafe-onedomain-noadmin", "danger-onedomain-fullreplay"])
@pytest.mark.parametrize("host", ["archivebox.localhost", "demo.archivebox.localhost", "archive.example.test"])
def test_single_domain_mode_serves_configured_public_hosts(client, mode, host):
    configure_hosts(mode=mode)
    response = client.get("/public/", HTTP_HOST=f"{host}:5797")
    assert response.status_code == 200


@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "auto"])
def test_builtin_role_and_original_replay_hosts_keep_existing_routing(snapshot, client, mode):
    configure_hosts(mode=mode)
    base = client.get("/public/?tag=example", HTTP_HOST="archivebox.localhost:5797")
    assert base.status_code == 302
    assert base["Location"] == "http://web.archivebox.localhost:5797/public/?tag=example"
    snapshot.permissions = "unlisted"
    snapshot.save(update_fields=["permissions"])
    output = save_output(snapshot, "singlefile")
    suffix = str(snapshot.id).replace("-", "")[-12:]
    replay = client.get(f"/singlefile/{output.output_str}", HTTP_HOST=f"snap-{suffix}.archivebox.localhost:5797")
    assert replay.status_code == 200
    assert b"ArchiveBox consolelog preview fixture" in b"".join(replay.streaming_content)
    assert client.get("/admin/login/", HTTP_HOST="admin.archivebox.localhost:5797").status_code == 200
    api = client.get("/", HTTP_HOST="api.archivebox.localhost:5797")
    assert api.status_code == 302
    assert api["Location"] == "/api/"
    assert client.get("/", HTTP_HOST="missing-original.archivebox.localhost:5797").status_code == 404


def test_trusted_preview_csp_includes_only_configured_public_origins(snapshot, client):
    configure_hosts()
    snapshot.permissions = "unlisted"
    snapshot.save(update_fields=["permissions"])
    output = save_output(snapshot, "singlefile")
    suffix = str(snapshot.id).replace("-", "")[-12:]
    response = client.get(
        f"/_card/{output.id}",
        HTTP_HOST=f"snap-{suffix}.archivebox.localhost:5797",
        HTTP_REFERER="http://attacker.example.test/",
    )
    assert response.status_code == 200
    ancestors = response["Content-Security-Policy"].split("frame-ancestors ")[1].split(";")[0].split()
    assert set(ancestors) == {
        "'self'",
        "http://archivebox.localhost:5797",
        "http://web.archivebox.localhost:5797",
        "http://admin.archivebox.localhost:5797",
        "http://demo.archivebox.localhost:5797",
        "http://archive.example.test:5797",
    }


@pytest.mark.parametrize(
    "allowed,host,status",
    [
        (".publisher.test", "alias.publisher.test", 200),
        (".publisher.test", "publisher.test", 200),
        (".publisher.test", "notpublisher.test", 400),
        ("*", "arbitrary.test", 200),
    ],
)
def test_standard_django_allowed_host_patterns(client, allowed, host, status):
    configure_hosts(mode="safe-onedomain-nojsreplay", allowed=allowed)
    assert client.get("/public/", HTTP_HOST=host).status_code == status


def test_wildcard_admission_does_not_allow_arbitrary_frame_ancestors(snapshot, client):
    configure_hosts(allowed="*")
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    output = save_output(snapshot, "singlefile")
    suffix = str(snapshot.id).replace("-", "")[-12:]
    response = client.get(f"/_card/{output.id}", HTTP_HOST=f"snap-{suffix}.archivebox.localhost:5797")
    ancestors = response["Content-Security-Policy"].split("frame-ancestors ")[1].split(";")[0].split()
    assert set(ancestors) == {
        "'self'",
        "http://archivebox.localhost:5797",
        "http://web.archivebox.localhost:5797",
        "http://admin.archivebox.localhost:5797",
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay"])
def test_public_alias_previews_render_in_real_browser(snapshot, admin_user, live_server, browser_runtime, tmp_path, mode):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright

    port = urlsplit(live_server.url).port
    configure_hosts(mode=mode, allowed="demo.archivebox.localhost,publisher.localhost")
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    save_output(snapshot, "singlefile")
    import shutil
    from pathlib import Path
    from archivebox.core.models import ArchiveResult
    from archivebox.tests.conftest import REPO_ROOT

    image = Path(snapshot.output_dir) / "screenshot/screenshot.png"
    image.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "publicsite/assets/social-card.png", image)
    output = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="screenshot",
        status="succeeded",
        output_str=image.name,
        output_files={image.name: {"size": image.stat().st_size, "mimetype": "image/png"}},
        output_size=image.stat().st_size,
    )
    snapshot.status = "sealed"
    snapshot.save(update_fields=["status"])
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        for alias in ("demo.archivebox.localhost", "publisher.localhost"):
            response = page.goto(f"http://{alias}:{port}/public/")
            assert response.status == 200
            assert urlsplit(page.url).hostname == alias
            card = page.locator(f'iframe[src*="/_card/{output.id}"]')
            card.scroll_into_view_if_needed()
            card_frame = card.element_handle().content_frame()
            card_frame.locator("img").wait_for()
            card_frame.wait_for_function("Array.from(document.images).some(image => image.complete && image.naturalWidth > 0)")
            response = page.goto(f"http://{alias}:{port}{snapshot.get_absolute_url()}/index.html")
            assert response.status == 200
            main = page.frame_locator("#main-frame")
            main.get_by_text("ArchiveBox consolelog preview fixture", exact=False).wait_for()
            assert main.get_by_text("ArchiveBox consolelog preview fixture", exact=False).is_visible()
            page.screenshot(path=str(tmp_path / f"{mode}-{alias}.png"))
        assert not any("frame-ancestors" in message for message in errors), errors
        if mode == "safe-subdomains-fullreplay":
            page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/admin/")
            page.locator('input[name="username"]').fill(admin_user.username)
            page.locator('input[name="password"]').fill("testpassword")
            page.locator('button[type="submit"], input[type="submit"]').click()
            page.wait_for_url(f"http://admin.archivebox.localhost:{port}/admin/")
            cookies = page.context.cookies([f"http://admin.archivebox.localhost:{port}/"])
            assert any(cookie["name"].startswith("archivebox_sessionid_") for cookie in cookies)
            suffix = str(snapshot.id).replace("-", "")[-12:]
            for host in ("web.archivebox.localhost", "demo.archivebox.localhost", f"snap-{suffix}.archivebox.localhost"):
                cookies = page.context.cookies([f"http://{host}:{port}/"])
                # The existing GMT_OFFSET preference is not authentication.
                assert {cookie["name"]: cookie["value"] for cookie in cookies if cookie["name"] != "GMT_OFFSET"} == {
                    "archivebox_admin_logged_in": "1",
                }
            assert {cookie["name"] for cookie in page.context.cookies([f"http://publisher.localhost:{port}/"])} <= {"GMT_OFFSET"}
        browser.close()


def test_missing_base_url_never_derives_allowed_roles_from_untrusted_host(client):
    configure_hosts(allowed="archive.example.test")
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": ""}
    machine.save(update_fields=["config"])
    for host in ("admin.attacker.test", "api.attacker.test", "snap-123456789abc.attacker.test"):
        assert client.get("/public/", HTTP_HOST=host).status_code == 400


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay"])
def test_explicit_startup_allowlist_admits_base_url_without_wildcard(tmp_path, mode):
    from archivebox.tests.conftest import init_archive, run_python_cwd

    init_archive(tmp_path)
    script = f"""
import os
os.environ.update(BASE_URL="http://canonical.example.test:5797", ALLOWED_HOSTS="alias.example.test", SERVER_SECURITY_MODE={mode!r})
import django
django.setup()
from django.test import Client
from django.conf import settings
client = Client()
for host in ("canonical.example.test", "alias.example.test"):
    response = client.get("/public/", HTTP_HOST=host + ":5797")
    if {mode!r} == "safe-subdomains-fullreplay" and host == "canonical.example.test":
        assert response.status_code == 302, (host, response.status_code)
        assert response["Location"] == "http://web.canonical.example.test:5797/public/"
        assert client.get("/public/", HTTP_HOST="web.canonical.example.test:5797").status_code == 200
    else:
        assert response.status_code == 200, (host, response.status_code)
assert client.get("/public/", HTTP_HOST="other.example.test:5797").status_code == 400
assert "canonical.example.test" in settings.ALLOWED_HOSTS
if {mode!r} == "safe-onedomain-nojsreplay":
    assert "*" not in settings.ALLOWED_HOSTS
print("startup host policy passed")
"""
    stdout, stderr, code = run_python_cwd(script, tmp_path)
    assert code == 0, stdout + stderr
    assert "startup host policy passed" in stdout
