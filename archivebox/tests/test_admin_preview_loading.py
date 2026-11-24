"""Admin screenshot previews load after paint, including below the fold."""

import re
import shutil
from pathlib import Path

import pytest
from django.template import Context
from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.test_snapshot_output_stacks import save_output

pytestmark = pytest.mark.django_db


def test_admin_preview_loader_uses_release_cache_key(admin_client):
    response = admin_client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    version = response.context["STATIC_CACHE_KEY"]
    assert f'/static/v/{version}/admin-snapshot-previews.js"' in response.content.decode()


def test_admin_thumbnail_uses_an_image_and_public_thumbnail_uses_the_card(snapshot):
    from archivebox.core.models import ArchiveResult
    from archivebox.core.templatetags.core_tags import snapshot_thumbnail

    output = snapshot.output_dir / "screenshot/capture.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).parents[2] / "publicsite/assets/social-card.png", output)
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="screenshot",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="screenshot/capture.png",
        output_files={"capture.png": {"size": output.stat().st_size, "mimetype": "image/png"}},
    )
    snapshot._snapshot_card_results = [result]
    snapshot._snapshot_thumbnail_result = result
    admin_html = str(snapshot_thumbnail(Context(), snapshot, admin=True))
    assert "<template data-admin-preview>" in admin_html
    assert "<img " in admin_html
    assert "screenshot/capture.png" in admin_html
    assert "<iframe" not in admin_html
    assert "snapshot-thumbnail-initial" in admin_html
    public_html = str(snapshot_thumbnail(Context(), snapshot))
    assert "<template data-admin-preview>" not in public_html
    assert f"_card/{result.pk}" in public_html
    assert 'sandbox="allow-scripts allow-same-origin"' in public_html


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("view", ["admin", "public"])
def test_thumbnail_card_covers_the_initial_only_when_it_has_content(snapshot, admin_user, live_server, browser_runtime, tmp_path, view):
    from urllib.parse import urlsplit
    from playwright.sync_api import expect, sync_playwright
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}", "PUBLIC_INDEX": True}
    machine.save(update_fields=["config"])
    responses_snapshot = Snapshot.objects.create(
        url="https://responses.example/",
        title="Captured responses",
        crawl=snapshot.crawl,
        config={"PERMISSIONS": "public"},
    )
    save_output(responses_snapshot, "responses")
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
        working = page.get_by_role("img", name="Preview of available.example", exact=True)
        responses = page.get_by_role("img", name="Preview of responses.example", exact=True)
        if view == "admin":
            for thumbnail, initial in ((broken, "M"), (working, "A"), (responses, "R")):
                expect(thumbnail.locator("iframe, img")).to_have_count(0)
                expect(thumbnail.locator(".snapshot-thumbnail-initial")).to_have_text(initial)
            browser.close()
            return
        broken.scroll_into_view_if_needed()
        expect(broken.frame_locator("iframe").locator(".favicon-thumbnail")).to_have_count(0)
        expect(broken.locator(".snapshot-thumbnail-initial")).to_have_text("M")
        overlay = broken.locator(':scope > span[aria-hidden="true"]')
        assert overlay.evaluate("node => getComputedStyle(node).backgroundColor") == "rgba(0, 0, 0, 0)"
        expect(broken.frame_locator("iframe").locator("body")).to_have_css("background-color", "rgba(0, 0, 0, 0)")
        working.scroll_into_view_if_needed()
        icon = working.frame_locator("iframe").locator(".favicon-thumbnail img")
        expect(icon).to_be_visible()
        expect(icon).to_have_js_property("naturalWidth", 28)
        responses.scroll_into_view_if_needed()
        card = responses.frame_locator("iframe")
        expect(card.get_by_text("Captured responses", exact=True)).to_be_visible()
        expect(card.locator("body")).not_to_have_css("background-color", "rgba(0, 0, 0, 0)")
        page.screenshot(path=str(tmp_path / f"{view}-favicon-fallback.png"))
        assert not errors
        browser.close()


@pytest.mark.django_db(transaction=True)
def test_admin_previews_load_without_scrolling_and_after_panel_navigation(snapshot, admin_user, live_server, browser_runtime):
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
        from archivebox.core.models import ArchiveResult

        output = Path(row.output_dir) / "screenshot/screenshot.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).parents[2] / "publicsite/assets/social-card.png", output)
        files = {"screenshot.png": {"size": output.stat().st_size, "mimetype": "image/png"}}
        if index == 49:
            files["missing.png"] = files["screenshot.png"]
        ArchiveResult.objects.create(
            snapshot=row,
            plugin="screenshot",
            status="succeeded",
            output_str="screenshot/missing.png" if index == 49 else "screenshot/screenshot.png",
            output_files=files,
            output_size=output.stat().st_size,
        )
    origin = f"http://admin.archivebox.localhost:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        requests = []
        page.on(
            "request",
            lambda request: (
                requests.append(request.url) if "/preview/screenshot/" in urlsplit(request.url).path or "/_card/" in request.url else None
            ),
        )
        page.goto(f"{origin}/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.locator('input[type="submit"]').click()
        page.wait_for_url(f"{origin}/admin/")
        requests.clear()
        page.goto(f"{origin}/admin/core/snapshot/", wait_until="load")
        images = page.locator(".snapshot-thumbnail img:not([hidden])")
        expect(images).to_have_count(50)
        expect(page.locator(".snapshot-thumbnail iframe")).to_have_count(0)
        last_thumbnail = page.locator(".snapshot-thumbnail").last
        assert last_thumbnail.evaluate("node => node.getBoundingClientRect().top > innerHeight")
        assert page.evaluate("scrollY") == 0
        assert images.last.evaluate("image => image.naturalWidth") > 0
        assert images.first.evaluate("image => image.naturalWidth") > 0
        expect(images.first).to_have_attribute("src", re.compile(r"/screenshot/screenshot\.png\?"))
        assert len(requests) == 51
        assert any("/screenshot/missing.png?" in url for url in requests)
        assert all("/_card/" not in url for url in requests)
        expect(last_thumbnail.locator(".snapshot-thumbnail-initial")).to_be_hidden()
        assert page.evaluate("""() => {
            const paint = performance.getEntriesByName('first-contentful-paint')[0].startTime;
            const images = performance.getEntriesByType('resource').filter(entry => entry.name.includes('/preview/screenshot/'));
            return images.length > 0 && images.every(image => image.startTime >= paint);
        }""")
        page.goto(f"{origin}/admin/core/snapshot/?view=grid", wait_until="load")
        expect(images.first).to_be_visible()
        # Replace the panel via the real search stream, without reloading.
        old_row = page.locator(".snapshot-thumbnail").first.element_handle()
        page.locator('#changelist-search [role="combobox"]').fill("meta:preview")
        page.locator('#changelist-search [role="combobox"]').press("Enter")
        page.wait_for_function("row => !row.isConnected", arg=old_row)
        expect(page.locator("#changelist-search")).not_to_have_attribute("aria-busy", "true")
        expect(images).to_have_count(50)
        # Without JS, the original visible letter/icon and native anchor remain.
        nojs = browser.new_context(java_script_enabled=False, storage_state=page.context.storage_state())
        fallback = nojs.new_page()
        fallback.goto(f"{origin}/admin/core/snapshot/", wait_until="load")
        expect(fallback.locator(".snapshot-thumbnail img")).to_have_count(0)
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
