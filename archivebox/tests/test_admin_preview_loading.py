"""Admin preview navigation is viewport bounded, without changing replay URLs."""

import re
import pytest
from django.template import Context
from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.test_snapshot_output_stacks import save_output

pytestmark = pytest.mark.django_db


def test_admin_preview_loader_uses_release_cache_key(admin_client):
    from django.utils.http import urlencode

    response = admin_client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    query = urlencode({"v": response.context["STATIC_CACHE_KEY"]})
    assert f'/static/admin-snapshot-previews.js?{query}"' in response.content.decode()


def test_only_admin_thumbnail_defers_card_navigation(snapshot):
    from archivebox.core.templatetags.core_tags import snapshot_thumbnail

    result = save_output(snapshot, "singlefile")
    snapshot._snapshot_thumbnail_result = result
    for admin in (False, True):
        html = str(snapshot_thumbnail(Context(), snapshot, admin=admin))
        first = re.search(r"<iframe[^>]+>", html).group()
        assert ("<template data-admin-preview>" in html) == admin
        assert ' src="' in first
        assert f"_card/{result.pk}" in first
        assert 'sandbox="allow-scripts allow-same-origin"' in first
        assert 'loading="lazy"' in first
        assert "<noscript>" not in html
        assert "snapshot-thumbnail-initial" in html


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("view", ["admin", "public"])
def test_missing_favicon_card_reveals_existing_hostname_initial(snapshot, admin_user, live_server, browser_runtime, tmp_path, view):
    from urllib.parse import urlsplit
    from playwright.sync_api import expect, sync_playwright
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}", "PUBLIC_INDEX": True}
    machine.save(update_fields=["config"])
    for host, available in (("missing.example", False), ("available.example", True)):
        saved = Snapshot.objects.create(url=f"https://{host}/", title=host, crawl=snapshot.crawl, config={"PERMISSIONS": "public"})
        content = b'<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28"><rect width="28" height="28" fill="green"/></svg>'
        if available:
            output = saved.output_dir / "favicon/favicon.svg"
            output.parent.mkdir(parents=True)
            output.write_bytes(content)
        ArchiveResult.objects.create(
            snapshot=saved,
            plugin="favicon",
            status="succeeded",
            output_str="favicon.svg",
            output_files={"favicon.svg": {"size": len(content), "mimetype": "image/svg+xml"}},
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        if view == "admin":
            origin = f"http://admin.archivebox.localhost:{port}"
            page.goto(f"{origin}/admin/login/")
            page.locator('[name="username"]').fill(admin_user.username)
            page.locator('[name="password"]').fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            target = f"{origin}/admin/core/snapshot/"
        else:
            target = f"http://archivebox.localhost:{port}/public/"
        page.goto(target)
        broken = page.get_by_role("img", name="Preview of missing.example", exact=True)
        broken.scroll_into_view_if_needed()
        expect(broken.frame_locator("iframe").locator(".favicon-thumbnail")).to_have_count(0)
        expect(broken.locator(".snapshot-thumbnail-initial")).to_have_text("M")
        overlay = broken.locator(':scope > span[aria-hidden="true"]')
        assert overlay.evaluate("node => getComputedStyle(node).backgroundColor") == "rgba(0, 0, 0, 0)"
        working = page.get_by_role("img", name="Preview of available.example", exact=True)
        working.scroll_into_view_if_needed()
        icon = working.frame_locator("iframe").locator(".favicon-thumbnail img")
        expect(icon).to_be_visible()
        expect(icon).to_have_js_property("naturalWidth", 28)
        page.screenshot(path=str(tmp_path / f"{view}-favicon-fallback.png"))
        assert not errors
        browser.close()


@pytest.mark.django_db(transaction=True)
def test_admin_previews_load_on_scroll_and_panel_navigation(snapshot, admin_user, live_server, browser_runtime):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    for index in range(50):
        row = Snapshot.objects.create(url=f"https://example.com/preview/{index}", crawl=snapshot.crawl)
        from pathlib import Path
        import shutil
        from archivebox.core.models import ArchiveResult

        output = Path(row.output_dir) / "screenshot/screenshot.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).parents[2] / "publicsite/assets/social-card.png", output)
        ArchiveResult.objects.create(
            snapshot=row,
            plugin="screenshot",
            status="succeeded",
            output_str="screenshot/screenshot.png",
            output_files={"screenshot.png": {"size": output.stat().st_size, "mimetype": "image/png"}},
            output_size=output.stat().st_size,
        )
    origin = f"http://admin.archivebox.localhost:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        requests = []
        page.on("request", lambda request: requests.append(request.url) if "/_card/" in request.url else None)
        page.goto(f"{origin}/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.locator('input[type="submit"]').click()
        page.wait_for_url(f"{origin}/admin/")
        requests.clear()
        page.goto(f"{origin}/admin/core/snapshot/", wait_until="load")
        frames = page.locator(".snapshot-thumbnail iframe")
        expect(frames.first).to_have_attribute("src", re.compile(r"/_card/"))
        print("INITIAL", {"assigned": page.locator(".snapshot-thumbnail iframe[src]").count(), "card_requests": len(requests)})
        assert len(requests) < 25
        assert page.locator(".snapshot-thumbnail iframe[src]").count() < 25
        assert frames.count() + page.locator(".snapshot-thumbnail template[data-admin-preview]").count() == 50
        last_thumbnail = page.locator(".snapshot-thumbnail").last
        assert last_thumbnail.locator("iframe").count() == 0
        template = last_thumbnail.locator("template[data-admin-preview]")
        target = template.evaluate("node => node.content.querySelector('iframe').src")
        last_thumbnail.scroll_into_view_if_needed()
        expect(last_thumbnail.locator("iframe")).to_have_attribute("src", target)
        expect(template).to_have_count(0)
        page.wait_for_load_state("networkidle")
        print(
            "SCROLLED",
            {
                "assigned": page.locator(".snapshot-thumbnail iframe[src]").count(),
                "card_requests": len(requests),
                "target_requested": target in requests,
            },
        )
        assert target in requests
        page.goto(f"{origin}/admin/core/snapshot/?view=grid", wait_until="load")
        expect(page.locator(".snapshot-thumbnail iframe").first).to_have_attribute("src", re.compile(r"/_card/"))
        # Replace the panel via the real search stream, without reloading.
        old_row = page.locator(".snapshot-thumbnail").first.element_handle()
        page.locator('#changelist-search [role="combobox"]').fill("meta:preview")
        page.locator('#changelist-search [role="combobox"]').press("Enter")
        page.wait_for_function("row => !row.isConnected", arg=old_row)
        expect(page.locator(".snapshot-thumbnail iframe").first).to_have_attribute("src", re.compile(r"/_card/"))
        expect(page.locator("#changelist-search")).not_to_have_attribute("aria-busy", "true")
        page.wait_for_load_state("networkidle")
        expect(page.locator(".snapshot-thumbnail iframe").first).to_have_attribute("src", re.compile(r"/_card/"))
        print("PARTIAL_SEARCH", {"assigned": page.locator(".snapshot-thumbnail iframe[src]").count()})
        assert page.locator(".snapshot-thumbnail iframe[src]").count() < 25
        # Without JS, the original visible letter/icon and native anchor remain.
        nojs = browser.new_context(java_script_enabled=False, storage_state=page.context.storage_state())
        fallback = nojs.new_page()
        fallback.goto(f"{origin}/admin/core/snapshot/", wait_until="load")
        expect(fallback.locator(".snapshot-thumbnail iframe[src]")).to_have_count(0)
        expect(fallback.locator(".snapshot-thumbnail template[data-admin-preview]")).to_have_count(50)
        expect(fallback.locator(".snapshot-thumbnail iframe")).to_have_count(0)
        thumbnail = fallback.locator(".snapshot-thumbnail").first
        assert thumbnail.is_visible()
        assert thumbnail.locator(".snapshot-thumbnail-initial").is_visible()
        link = thumbnail.locator("xpath=..").get_attribute("href")
        assert link
        with fallback.expect_navigation() as navigation:
            thumbnail.click()
        from urllib.parse import urljoin

        assert fallback.url == urljoin(origin, link)
        assert navigation.value.status == 200
        print("NOJS", {"letter_visible": True, "native_link_opened": True, "inert_templates": 50})
        nojs.close()
        browser.close()
