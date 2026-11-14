"""Rendered metadata and accessibility through real detail/list/form routes."""

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from lxml.html import fromstring

from archivebox.core.models import ArchiveResult
from archivebox.tests.conftest import ADMIN_TEST_HOST, WEB_TEST_HOST

pytestmark = pytest.mark.django_db


def save_output(snapshot, plugin, name, content, mimetype):
    path = Path(snapshot.output_dir) / plugin / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=plugin,
        status="succeeded",
        output_str=name,
        output_files={name: {"size": path.stat().st_size, "mimetype": mimetype}},
    )


def detail(client, snapshot):
    response = client.get(snapshot.get_absolute_url() + "/index.html", HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200, response.content[:500]
    return fromstring(response.content.decode())


def test_snapshot_social_metadata(client, snapshot):
    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.title = "Saved title"
    snapshot.save()
    seo = {
        "og:title": 'Article "title" & more',
        "og:description": "<b>Readable</b> &amp; useful",
        "canonical": "https://unrelated.example/",
    }
    save_output(snapshot, "seo", "seo.json", json.dumps(seo), "application/json")
    image = (Path(__file__).parents[1] / "templates/static/archive.png").read_bytes()
    save_output(snapshot, "screenshot", "screenshot.png", image, "image/png")
    soup = detail(client, snapshot)
    assert soup.xpath('//link[@rel="canonical"]/@href')[0] == snapshot.url
    assert soup.xpath('//meta[@property="og:title"]/@content')[0] == seo["og:title"]
    assert soup.xpath('//meta[@property="og:description"]/@content')[0] == "Readable & useful"
    assert soup.xpath('//meta[@property="og:url"]/@content')[0].startswith("http://web.archivebox.localhost:")
    assert soup.xpath('//meta[@name="twitter:card"]/@content')[0] == "summary_large_image"
    image_url = soup.xpath('//meta[@property="og:image"]/@content')[0]
    parsed = urlsplit(image_url)
    response = client.get(parsed.path + "?" + parsed.query, HTTP_HOST=parsed.netloc)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("image/png")
    assert b"".join(response.streaming_content) == image
    assert soup.xpath('//iframe[@id="main-frame"]/@title')[0]
    assert soup.xpath('//main | //*[@role="main"]')
    assert soup.xpath('//h1 | //*[@role="heading"][@aria-level="1"]')
    assert soup.xpath("//a[@download]/@aria-label")[0].startswith("Download ")


@pytest.mark.parametrize("seo_content", ["{broken", "[]", '{"description": {"wrong": "type"}}'])
def test_metadata_falls_back_to_saved_article(client, snapshot, seo_content):
    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.title = "Saved title"
    snapshot.save()
    save_output(snapshot, "seo", "seo.json", seo_content, "application/json")
    save_output(
        snapshot,
        "readability",
        "article.json",
        json.dumps({"title": "Article title", "excerpt": "Article excerpt"}),
        "application/json",
    )
    soup = detail(client, snapshot)
    assert soup.xpath('//meta[@property="og:description"]/@content')[0] == "Article excerpt"
    assert soup.xpath('//meta[@property="og:title"]/@content')[0] == "Article title"
    assert not soup.xpath('//meta[@property="og:image"]')
    assert soup.xpath('//meta[@name="twitter:card"]/@content')[0] == "summary"


def test_plain_text_metadata_and_private_access(client, snapshot):
    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.save()
    save_output(snapshot, "htmltotext", "htmltotext.txt", "A useful article.\n\n" + "More words. " * 100, "text/plain")
    soup = detail(client, snapshot)
    description = soup.xpath('//meta[@property="og:description"]/@content')[0]
    assert description.startswith("A useful article. More words.")
    assert len(description) <= 300
    snapshot.config = {**snapshot.config, "PERMISSIONS": "private"}
    snapshot.save()
    response = client.get(snapshot.get_absolute_url() + "/index.html", HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code in (302, 403, 404)
    assert b"A useful article" not in response.content


def test_main_form_accessible_names(admin_client):
    for path in ("/admin/core/snapshot/", "/admin/personas/persona/add/", "/add/"):
        response = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST, follow=True)
        assert response.status_code == 200
        soup = fromstring(response.content.decode())
        if search := soup.xpath('//*[@id="searchbar"]'):
            assert search[0].get("aria-label") or soup.xpath('//label[@for="searchbar"]')
        assert not soup.xpath('//*[@role="submit"]')


@pytest.mark.django_db(transaction=True)
def test_browser_accessibility_tree_and_keyboard(snapshot, admin_user, live_server, browser_runtime, tmp_path):
    from playwright.sync_api import sync_playwright
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    base = f"http://archivebox.localhost:{port}"
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": base, "PUBLIC_INDEX": True}
    machine.save(update_fields=["config"])
    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.title = "Accessibility test article"
    snapshot.save()
    save_output(snapshot, "htmltotext", "htmltotext.txt", "Accessible archived article", "text/plain")
    save_output(
        snapshot,
        "seo",
        "seo.json",
        json.dumps({"title": "Accessible article", "description": "Article description"}),
        "application/json",
    )
    admin_user.set_password("accessibility-test-password")
    admin_user.save()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page()
            page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("accessibility-test-password")
            page.locator('input[type="submit"]').click()
            page.wait_for_url("**/admin/")
            cdp = page.context.new_cdp_session(page)
            routes = [
                ("admin", "/admin/core/snapshot/"),
                ("admin", "/admin/core/snapshot/grid/"),
                ("web", "/public/"),
                ("admin", "/add/"),
                ("admin", "/admin/personas/persona/add/"),
                ("web", snapshot.get_absolute_url() + "/index.html"),
            ]
            for host, path in routes:
                response = page.goto(f"http://{host}.archivebox.localhost:{port}{path}", wait_until="networkidle")
                assert response.status == 200, (path, response.status)
                tree = cdp.send("Accessibility.getFullAXTree")["nodes"]
                controls = [
                    node
                    for node in tree
                    if not node.get("ignored")
                    and node.get("role", {}).get("value") in {"button", "textbox", "combobox", "checkbox", "link"}
                ]
                unnamed = [
                    {
                        "role": node["role"]["value"],
                        "html": cdp.send("DOM.getOuterHTML", {"backendNodeId": node["backendDOMNodeId"]})["outerHTML"][:400],
                    }
                    for node in controls
                    if not node.get("name", {}).get("value", "").strip()
                ]
                assert not unnamed, (path, unnamed)
                assert any(node.get("role", {}).get("value") == "main" and not node.get("ignored") for node in tree), path
                if path in ("/add/", "/admin/personas/persona/add/"):
                    config = page.locator(".plugin-config-marker:visible").first
                    config.focus()
                    page.keyboard.press("Enter")
                    assert config.get_attribute("aria-expanded") == "true"
                    page.keyboard.press("Space")
                    assert config.get_attribute("aria-expanded") == "false"
            # Screen readers see the current output and named embedded viewer.
            toggle = page.locator(".header-toggle")
            if toggle.get_attribute("aria-expanded") == "false":
                toggle.click()
            stack = page.locator(".output-stack-article_text")
            stack.click()
            assert stack.get_attribute("aria-expanded") == "true"
            preview = page.locator('.stack-tray .thumb-body a[target="preview"]').first
            preview.click()
            assert preview.get_attribute("aria-current") == "true"
            viewer = page.locator("#main-frame").content_frame
            viewer.get_by_role("article").filter(has_text="Accessible archived article").wait_for()
            assert viewer.get_by_role("link", name="View raw", exact=True).count() == 1
            page.get_by_role("button", name="Collapse stack", exact=True).click()
            assert stack.get_attribute("aria-expanded") == "false"
            assert stack.evaluate("e => e === document.activeElement")
            assert page.locator("#main-frame").get_attribute("title").startswith("Archived content:")
            (tmp_path / "accessibility-tree.json").write_text(json.dumps(cdp.send("Accessibility.getFullAXTree"), indent=2))
            page.screenshot(path=str(tmp_path / "snapshot-accessibility.png"))
        finally:
            browser.close()


def test_missing_artifacts_and_static_export_metadata(client, snapshot, tmp_path):
    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.title = 'Saved "title" & text'
    snapshot.save()
    result = save_output(snapshot, "seo", "seo.json", '{"description":"must not escape snapshot root"}', "application/json")
    source = Path(snapshot.output_dir) / "seo/seo.json"
    outside = tmp_path / "outside.json"
    source.rename(outside)
    source.symlink_to(outside)
    soup = detail(client, snapshot)
    assert soup.xpath('//meta[@property="og:title"]/@content')[0] == snapshot.title
    assert soup.xpath('//meta[@property="og:description"]/@content')[0] == f"Archived snapshot of {snapshot.url}"
    source.unlink()
    result.status = "failed"
    result.save()
    soup = detail(client, snapshot)
    assert not soup.xpath('//meta[@property="og:image"]')
    snapshot.write_html_details(out_dir=tmp_path / "export")
    exported = fromstring((tmp_path / "export/index.html").read_text())
    assert exported.xpath('//link[@rel="canonical"]/@href') == [snapshot.url]
    assert not exported.xpath('//meta[@property="og:url"] | //meta[@property="og:image"]')


def test_plugin_ui_discovers_snapshot_head_fragments(snapshot):
    from django.template import Context, Template

    snapshot.title = "Plugin supplied title"
    snapshot.save()
    save_output(snapshot, "seo", "seo.json", '{"og:title":"Registered SEO fragment"}', "application/json")
    context = Context(snapshot.get_html_details_context())
    original_title = context["title"]
    discovered = Template('{% load core_tags %}{% plugin_ui "snapshot_head" %}').render(context)
    explicit = Template('{% load core_tags %}{% plugin_ui "seo" "snapshot_head" %}').render(context)
    assert discovered == explicit
    assert fromstring(discovered).xpath('//meta[@property="og:title"]/@content') == ["Registered SEO fragment"]
    assert context["title"] == original_title
    assert Template('{% load core_tags %}{% plugin_ui "nonexistent_slot" %}').render(context) == ""


def test_seo_presentation_uses_plain_snapshot_context(snapshot, django_assert_num_queries):
    from abx_plugins.plugins.seo.presentation import template_context

    save_output(snapshot, "seo", "seo.json", '{"og:title":"Plain artifact title"}', "application/json")
    failed = save_output(snapshot, "htmltotext", "htmltotext.txt", "Failed capture text", "text/plain")
    failed.status = "failed"
    failed.save(update_fields=["status"])
    image = Path(snapshot.output_dir) / "capture.png"
    image.write_bytes((Path(__file__).parents[1] / "templates/static/archive.png").read_bytes())
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="chrome_extension_viewport",
        status="succeeded",
        output_str="capture.png",
        output_files={"capture.png": {"size": image.stat().st_size, "mimetype": "image/png", "root_relative": True}},
    )
    context = snapshot.get_html_details_context()
    plain = json.loads(json.dumps({key: context[key] for key in ("url", "title", "output_dir", "output_files", "primary_preview_plugins")}))
    assert "htmltotext/htmltotext.txt" not in plain["output_files"]
    assert plain["output_files"]["capture.png"]["plugin"] == "chrome_extension_viewport"
    with django_assert_num_queries(0):
        metadata = template_context("snapshot_head", plain)["social"]
    assert metadata == {"title": "Plain artifact title", "description": f"Archived snapshot of {snapshot.url}", "image_path": "capture.png"}
