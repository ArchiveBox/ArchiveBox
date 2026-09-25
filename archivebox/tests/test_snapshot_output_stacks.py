"""Snapshot grouping uses real stored outputs, including portable exports."""

import shutil
import re
from pathlib import Path

import pytest
from django.contrib.auth.models import AnonymousUser
from django.template import Context
from django.test import RequestFactory

from archivebox.core.models import ArchiveResult
from archivebox.core.views import SnapshotView
from archivebox.config.common import ServerConfig
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db
FIXTURE = Path(__file__).parent / "fixtures" / "consolelog_preview.html"
IMAGE_FIXTURE = Path(__file__).parents[2] / "publicsite" / "assets" / "social-card.png"


@pytest.mark.parametrize("surface", ["admin", "static", "prefetched", "public", "started"])
def test_icon_piles_match_detail_stack_priority(snapshot, client, settings, surface):
    from django.contrib.admin.sites import AdminSite
    from archivebox.core.admin_snapshots import SnapshotAdmin
    from archivebox.core.models import Snapshot
    from archivebox.tests.conftest import WEB_TEST_HOST

    for plugin in (
        "htmltotext",
        "mercury",
        "trafilatura",
        "defuddle",
        "readability",
        "singlefile",
        "archivewebpage",
        "pdf",
        "screenshot",
        "responses",
        "papersdl",
        "forumdl",
        "git",
        "headers",
    ):
        save_output(snapshot, plugin)
    save_output(snapshot, "dns", hook="10", extra_files=("first.html",))
    save_output(snapshot, "dns", hook="20", extra_files=("second.html",))
    save_output(snapshot, "git", hook="60", extra_files=("extra.html",))
    expected_groups = [
        ["archivewebpage", "singlefile"],
        ["screenshot", "pdf"],
        ["readability", "defuddle", "mercury", "trafilatura", "htmltotext"],
        ["papersdl", "git", "forumdl", "responses"],
        ["dns", "headers"],
    ]
    detail = snapshot.get_html_details_context()["archiveresults"]
    assert [item["name"] for item in detail if item["name"] != "responses_html"] == [
        plugin for group in expected_groups for plugin in group
    ]

    if surface == "admin":
        model_admin = SnapshotAdmin(Snapshot, AdminSite())
        model_admin.request = RequestFactory().get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)
        model_admin.request.archivebox_config = ServerConfig()
        rendered = str(model_admin.files(snapshot))
    elif surface in {"public", "started"}:
        settings.PUBLIC_INDEX = True
        snapshot.permissions = "public"
        snapshot.status = Snapshot.StatusChoices.STARTED if surface == "started" else Snapshot.StatusChoices.SEALED
        snapshot.save()
        response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
        assert response.status_code == 200
        rendered = response.content.decode()
    else:
        if surface == "prefetched":
            snapshot = Snapshot.objects.prefetch_related("archiveresult_set").get(pk=snapshot.pk)
        rendered = str(snapshot.icons(quote_paths=True))

    # Each group contains its cover first, then popup members in priority order.
    assert re.findall(r'class="[^"\n]*files-icon-plugin--([\w-]+)', rendered) == [
        plugin for group in expected_groups for plugin in [group[0], *group]
    ]


@pytest.mark.parametrize(
    ("security_mode", "expected_host"),
    [
        ("safe-subdomains-fullreplay", "web.archivebox.localhost"),
        ("safe-onedomain-nojsreplay", "archivebox.localhost"),
    ],
)
def test_snapshot_detail_link_stays_on_web_origin(snapshot, security_mode, expected_host):
    from archivebox.core.templatetags.core_tags import snapshot_detail_url

    config = ServerConfig(BASE_URL="http://archivebox.localhost:5797", SERVER_SECURITY_MODE=security_mode)
    url = snapshot_detail_url(Context({"CONFIG": config}), snapshot)
    assert url == f"http://{expected_host}:5797{snapshot.get_absolute_url()}"
    assert (
        snapshot_detail_url(
            Context({"STATIC_EXPORT": True, "STATIC_EXPORT_DIR": snapshot.output_dir}),
            snapshot,
        )
        == "./index.html"
    )


def save_output(snapshot, plugin, filename="content.html", *, hook="50", extra_files=()):
    directory = Path(snapshot.output_dir) / plugin
    directory.mkdir(parents=True, exist_ok=True)
    for name in (filename, *extra_files):
        shutil.copyfile(FIXTURE, directory / name)
    files = {name: {"size": (directory / name).stat().st_size, "mimetype": "text/html"} for name in (filename, *extra_files)}
    return ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=plugin,
        hook_name=f"on_Snapshot__{hook}_{plugin}.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str=filename,
        output_files=files,
        output_size=sum(file["size"] for file in files.values()),
    )


def save_response_image(snapshot, filename="all/example.png"):
    path = Path(snapshot.output_dir) / "responses" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(IMAGE_FIXTURE, path)
    return ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="responses",
        hook_name="on_Snapshot__24_responses.daemon.bg.js",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str=filename,
        output_files={
            filename: {
                "size": path.stat().st_size,
                "mimetype": "image/png",
                "extension": "png",
            },
        },
        output_size=path.stat().st_size,
    )


def test_snapshot_groups_prefer_requested_plugins_and_keep_unclassified_outputs(snapshot):
    for plugin in (
        "dom",
        "singlefile",
        "wget",
        "mercury",
        "htmltotext",
        "defuddle",
        "readability",
        "liteparse",
        "trafilatura",
        "opendataloader",
        "papersdl",
        "custom_output",
        "archivewebpage",
        "chrome_mhtml",
        "responses",
        "pdf",
        "screenshot",
    ):
        save_output(snapshot, plugin)

    context = snapshot.get_html_details_context()
    groups = {group["id"]: group for group in context["output_groups"]}
    assert list(groups) == ["html", "raster", "article_text", "embedded_media", "metadata", "other"]
    outputs = context["archiveresults"]

    def names(group):
        return [output["name"] for output in outputs if output["output_group"] == group]

    assert names("html") == ["archivewebpage", "singlefile", "chrome_mhtml", "wget", "dom", "responses_html"]
    assert names("raster") == ["screenshot", "pdf"]
    assert names("article_text") == ["readability", "defuddle", "mercury", "trafilatura", "htmltotext", "opendataloader"]
    assert "liteparse" in names("embedded_media")
    assert "papersdl" in names("embedded_media")
    assert names("other") == ["custom_output"]
    assert context["best_result"]["name"] == "archivewebpage"


@pytest.mark.parametrize("larger_plugin", ["responses", "papersdl"])
def test_papersdl_is_above_responses_regardless_of_output_size(snapshot, larger_plugin):
    for plugin in ("responses", "papersdl"):
        save_output(snapshot, plugin, extra_files=("extra.html",) if plugin == larger_plugin else ())

    outputs = snapshot.get_html_details_context()["archiveresults"]
    media = [output for output in outputs if output["output_group"] == "embedded_media"]
    assert next(output for output in media if output["name"] == larger_plugin)["size"] == 2 * FIXTURE.stat().st_size
    assert [output["name"] for output in media] == ["papersdl", "responses"]


def test_equal_outputs_sort_by_whole_output_size_without_double_counting_hooks(snapshot):
    save_output(snapshot, "git", extra_files=("README.html", "license.html"))
    save_output(snapshot, "forumdl")
    save_output(snapshot, "gallerydl")
    save_output(snapshot, "dns", extra_files=("second.html",))
    save_output(snapshot, "headers")
    # Two hooks report an overlapping path. The second also captures another file.
    save_output(snapshot, "dns", hook="60", extra_files=("third.html",))
    context = snapshot.get_html_details_context()
    outputs = context["archiveresults"]
    assert [output["name"] for output in outputs if output["output_group"] == "embedded_media"] == ["git", "forumdl", "gallerydl"]
    metadata = [output for output in outputs if output["output_group"] == "metadata"]
    assert [output["name"] for output in metadata] == ["dns", "headers"]
    assert metadata[0]["size"] == 3 * FIXTURE.stat().st_size
    assert len(metadata[0]["result_ids"].split(",")) == 2


def test_stacks_render_live_and_static_without_losing_output_actions(snapshot, admin_user):
    result = save_output(snapshot, "defuddle")
    request = RequestFactory().get(f"/{snapshot.url_path}/index.html", HTTP_HOST=ADMIN_TEST_HOST)
    request.user = admin_user
    response = SnapshotView.render_live_index(request, snapshot)
    assert response.status_code == 200
    live_html = response.content.decode()
    assert 'data-output-group="article_text"' in live_html
    assert 'id="snapshot-output-groups"' in live_html
    assert f'data-archive-result-ids="{result.id}"' in live_html
    assert 'title="Download output file"' in live_html
    assert 'title="Open output folder"' in live_html
    assert 'title="Delete this output"' in live_html
    assert 'title="Browse the full SNAP_DIR for this snapshot"' not in live_html
    assert "See all files..." not in live_html
    assert 'aria-label="Search Archive.org"' in live_html

    request.user = AnonymousUser()
    assert 'title="Delete this output"' not in SnapshotView.render_live_index(request, snapshot).content.decode()

    snapshot.write_html_details()
    exported = (Path(snapshot.output_dir) / "index.html").read_text()
    assert 'data-output-group="article_text"' in exported
    assert 'href="./defuddle/content.html"' in exported
    assert 'title="Delete this output"' not in exported
    assert "initializeOutputStacks" in exported
    assert "localhost" not in exported


def test_filesystem_fallback_uses_directory_size_for_equal_outputs(snapshot):
    for plugin, count in (("gallerydl", 1), ("git", 3)):
        directory = Path(snapshot.output_dir) / plugin
        directory.mkdir(parents=True)
        for index in range(count):
            shutil.copyfile(FIXTURE, directory / f"page-{index}.html")
    context = snapshot.get_html_details_context(static_export_dir=Path(snapshot.output_dir))
    media = [output for output in context["archiveresults"] if output["output_group"] == "embedded_media"]
    assert [output["name"] for output in media] == ["git", "gallerydl"]
    assert media[0]["size"] == 3 * FIXTURE.stat().st_size


def test_responses_html_card_requires_saved_html_and_keeps_gallery(snapshot):
    result = save_output(snapshot, "responses")
    outputs = snapshot.get_html_details_context()["archiveresults"]
    cards = {output["name"]: output for output in outputs}
    assert cards["responses"]["output_group"] == "embedded_media"
    assert cards["responses_html"]["output_group"] == "html"
    assert cards["responses_html"]["path"] == "responses/content.html"
    assert cards["responses_html"]["direct_preview_path"] == "responses/content.html?card=responses_html"
    assert cards["responses_html"]["result"] is None
    assert sum(output["size"] for output in outputs) == result.output_size
    request = RequestFactory().get(f"/{snapshot.url_path}/index.html", HTTP_HOST=ADMIN_TEST_HOST)
    request.user = AnonymousUser()
    from django.template.loader import render_to_string

    html = render_to_string("core/snapshot_output_cards.html", snapshot.get_html_details_context(request=request), request=request)
    assert 'data-plugin-name="responses_html"' in html
    assert "responses/content.html?card=responses_html" in html
    assert "responses/content.html?preview=1" in html
    (Path(snapshot.output_dir) / "responses" / "data.json").write_text("{}")
    result.output_str = "data.json"
    result.output_files = {"data.json": {"size": 2, "mimetype": "application/json"}}
    result.save()
    assert "responses_html" not in {output["name"] for output in snapshot.get_html_details_context()["archiveresults"]}


@pytest.mark.parametrize(
    ("security_mode", "expected_host"),
    (
        ("safe-onedomain-nojsreplay", "archivebox.localhost:8937"),
        ("safe-subdomains-fullreplay", "snap-{snapshot_suffix}.archivebox.localhost:8937"),
    ),
)
def test_responses_card_uses_snapshot_origin_for_nested_preview_urls(snapshot, security_mode, expected_host):
    from archivebox.core.templatetags.core_tags import plugin_card

    result = save_response_image(snapshot)
    request = RequestFactory().get(
        f"/{snapshot.url_path}/index.html",
        secure=True,
        HTTP_HOST="archivebox.localhost:8937",
    )
    config = ServerConfig(BASE_URL="https://archivebox.localhost:8937", SERVER_SECURITY_MODE=security_mode)
    html = plugin_card(Context({"request": request, "CONFIG": config}), result)
    expected_host = expected_host.format(snapshot_suffix=str(snapshot.id)[-12:])
    assert f"https://{expected_host}/" in html
    assert f"_card/{result.id}" in html
    assert "/responses/all/example.png?raw=1" not in html


def test_responses_card_uses_relative_preview_urls_in_static_export(snapshot):
    from archivebox.core.templatetags.core_tags import plugin_card

    result = save_response_image(snapshot)
    html = plugin_card(
        Context({"STATIC_EXPORT": True, "STATIC_EXPORT_DIR": snapshot.output_dir}),
        result,
    )
    assert 'src="./responses/all/example.png?raw=1"' in html
    assert "localhost" not in html


@pytest.mark.django_db(transaction=True)
def test_stack_cover_and_expanded_card_load_same_document(snapshot, live_server):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    save_output(snapshot, "defuddle")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html")
        assert "{#" not in page.locator("body").inner_text()
        cover = page.locator(".output-stack-article_text .stack-cover .thumbnail-wrapper > iframe")
        cover_viewer = cover.content_frame.locator("iframe")
        cover_viewer.wait_for()
        cover_viewer.content_frame.locator("#reader").wait_for()
        assert cover.get_attribute("loading") == "lazy"
        assert cover.get_attribute("fetchpriority") == "low"
        source = cover.get_attribute("src")
        page.locator(".output-stack-article_text").click()
        expanded = page.locator('.stack-tray .thumb-card[data-plugin-name="defuddle"] .thumbnail-wrapper > iframe')
        expanded_viewer = expanded.content_frame.locator("iframe")
        expanded_viewer.wait_for()
        expanded_viewer.content_frame.locator("#reader").wait_for()
        assert expanded.get_attribute("loading") == "lazy"
        assert expanded.get_attribute("fetchpriority") == "low"
        assert expanded.get_attribute("src") == source
        assert cover_viewer.get_attribute("src") == expanded_viewer.get_attribute("src")
        assert cover_viewer.content_frame.locator("body > header").is_hidden()
        assert expanded_viewer.content_frame.locator("body > header").is_hidden()
        assert cover.bounding_box()["height"] > 0
        page.screenshot(path="/tmp/stack-cover-mobile.png")
        browser.close()


@pytest.mark.django_db(transaction=True)
def test_forumdl_card_and_full_view_render_saved_thread(snapshot, live_server):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{port}",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    output = Path(snapshot.output_dir) / "forumdl/forum.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).parent / "fixtures/forumdl/hn-thread.jsonl", output)
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="forumdl",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="forumdl/forum.jsonl",
    )
    host = get_snapshot_host(str(snapshot.id)).split(":")[0]
    viewer_url = f"http://{host}:{port}/forumdl/forum.jsonl?preview=1"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=[f"--host-resolver-rules=MAP {host} 127.0.0.1"])
        page = browser.new_page()
        page.goto(viewer_url)
        page.locator(".thread-title").wait_for()
        assert "Navier-Stokes" in page.locator(".thread-title").inner_text()
        assert page.locator(".comment").count() >= 1
        assert page.locator("body > header").is_visible()
        page.set_viewport_size({"width": 250, "height": 170})
        page.evaluate("window.scrollTo(0, 200)")
        assert page.evaluate("scrollY") > 0
        page.goto(f"{viewer_url}&titlebar=0")
        assert page.locator("body > header").is_hidden()
        assert page.locator("html").evaluate("e => getComputedStyle(e).overflowY") == "clip"
        assert page.locator(".thread-title").evaluate("e => getComputedStyle(e).overflowY") == "clip"
        page.evaluate("window.scrollTo(0, 200)")
        assert page.evaluate("scrollY") == 0
        page.goto(f"http://{host}:{port}/_card/{result.id}")
        embedded = page.locator("iframe")
        embedded.wait_for()
        assert page.locator("html").evaluate("e => getComputedStyle(e).overflowY") == "clip"
        assert embedded.get_attribute("src") == f"{viewer_url}&titlebar=0"
        embedded.content_frame.locator(".thread-title").wait_for()
        assert "Navier-Stokes" in embedded.content_frame.locator(".thread-title").inner_text()
        assert embedded.content_frame.locator("body > header").is_hidden()
        page.set_viewport_size({"width": 250, "height": 170})
        page.screenshot(path="/tmp/archivebox-forumdl-card-final.png")
        browser.close()


@pytest.mark.django_db(transaction=True)
def test_pdf_card_shows_pdf_fallback_without_any_preview_image(snapshot, live_server):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{port}",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    output = Path(snapshot.output_dir) / "pdf/output.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="pdf",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="pdf/output.pdf",
    )
    host = get_snapshot_host(str(snapshot.id)).split(":")[0]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=[f"--host-resolver-rules=MAP {host} 127.0.0.1"])
        page = browser.new_page(viewport={"width": 250, "height": 170})
        page.set_content("<h1>Archived page</h1>")
        output.write_bytes(page.pdf())
        page.goto(f"http://{host}:{port}/_card/{result.id}")
        page.wait_for_function("document.querySelector('#preview').complete && !document.querySelector('#preview').naturalWidth")
        assert page.locator("#fallback").is_visible()
        assert "PDF saved" in page.locator("#fallback").inner_text()
        assert page.locator("#fallback .icon").is_visible()
        assert page.locator(".label").count() == 0
        browser.close()


@pytest.mark.django_db(transaction=True)
def test_responsive_header_and_expanded_stack_keep_full_view_in_page_flow(snapshot, live_server, tmp_path):
    import zipfile
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    for plugin in ("readability", "defuddle", "mercury", "trafilatura", "htmltotext"):
        save_output(snapshot, plugin)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="pdf",
        hook_name="on_Snapshot__50_pdf.js",
        status=ArchiveResult.StatusChoices.FAILED,
    )
    expected_size = snapshot.get_html_details_context()["size"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"])
        page = browser.new_page()
        page.goto(f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html", wait_until="domcontentloaded")
        actions = page.locator(".header-url-actions")
        assert page.locator(".header-status").inner_text().split() == ["5", "1"]
        assert page.locator(".status-count-success").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(172, 212, 182)"
        assert page.locator(".status-count-failed").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(181, 42, 66)"
        assert actions.locator(".header-download-size").inner_text() == expected_size
        assert actions.locator(".header-url-action").count() == 5
        assert actions.locator(".header-url-action").evaluate_all("nodes => nodes.map(e => e.getAttribute('aria-label'))") == [
            "Copy original URL",
            "Open original URL",
            "Search Archive.org",
            "Edit snapshot",
            "Download snapshot ZIP",
        ]
        assert page.locator(".permission-pill").count() == 1
        assert actions.locator(".permission-pill").inner_text().endswith("PUBLIC")
        assert page.get_by_role("link", name="Search Archive.org", exact=True).count() == 1
        original = actions.get_by_role("link", name="Open original URL", exact=True)
        assert original.get_attribute("href") == snapshot.url
        assert original.get_attribute("target") == "_blank"
        assert (
            actions.get_by_role("link", name="Search Archive.org", exact=True).get_attribute("href")
            == f"https://web.archive.org/web/{snapshot.url}"
        )
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        actions.get_by_role("button", name="Copy original URL", exact=True).click()
        page.get_by_role("button", name="URL copied", exact=True).wait_for()
        assert page.evaluate("navigator.clipboard.readText()") == snapshot.url
        assert page.locator("#snapshot-output-browser").is_visible()
        with page.expect_download() as download_info:
            actions.locator(".header-url-download .header-status").click()
        archive_path = tmp_path / "snapshot.zip"
        download_info.value.save_as(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            for plugin in ("readability", "defuddle", "mercury", "trafilatura", "htmltotext"):
                assert any(f"/{plugin}/" in name for name in archive.namelist())
            assert archive.testzip() is None
        for width, height in ((1440, 1000), (1024, 900), (768, 1024), (600, 900), (390, 844), (320, 700)):
            page.set_viewport_size({"width": width, "height": height})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            logo = page.locator(".header-archivebox img").bounding_box()
            url = page.locator(
                ".header-url" if width > 1100 else ".header-url-location" if width > 600 else ".header-url-text",
            ).bounding_box()
            assert logo["x"] >= 0 and logo["width"] >= 30
            assert logo["x"] + logo["width"] <= url["x"]
            if width > 1100:
                assert url["x"] == 104
            favicon = page.locator(".header-url-favicon").bounding_box()
            assert favicon["width"] == favicon["height"] == 22
            if width > 600:
                assert favicon["x"] >= url["x"]
                assert favicon["x"] + favicon["width"] <= page.locator(".header-url-text").bounding_box()["x"]
            else:
                title_box = page.locator(".header-title-text").bounding_box()
                assert favicon["y"] >= url["y"] + url["height"]
                assert abs(favicon["y"] + favicon["height"] / 2 - title_box["y"] - title_box["height"] / 2) < 1
                assert not actions.locator("#copy-original-url").is_visible()
                assert not actions.get_by_role("link", name="Open original URL", exact=True).is_visible()
                assert not actions.locator(".permission-text").is_visible()
                assert "." not in actions.locator(".mobile-size").inner_text()
            if width > 480:
                assert url["height"] == 28
            if width > 1100:
                assert page.locator(".header-top").bounding_box()["height"] == 44
            assert page.locator(".header-url .header-title-text").count() == 1
            status_box = actions.locator(".header-status").bounding_box()
            permission_box = actions.locator(".permission-pill").bounding_box()
            assert status_box["height"] == 22
            assert permission_box["height"] == (22 if width > 1100 else 28)
            download_box = actions.locator(".header-url-download").bounding_box()
            assert status_box["x"] >= download_box["x"]
            assert status_box["x"] + status_box["width"] <= download_box["x"] + download_box["width"]
            assert actions.locator(".header-status").evaluate("e => e.tagName") == "SPAN"
            action_box = actions.bounding_box()
            if width > 1100:
                assert action_box["x"] >= url["x"]
                assert action_box["x"] + action_box["width"] <= url["x"] + url["width"]
            else:
                assert action_box["y"] >= url["y"] + url["height"]
                captures_box = page.locator(".header-capture-row").bounding_box()
                assert abs(captures_box["y"] - action_box["y"]) <= 1
                assert action_box["x"] + action_box["width"] <= captures_box["x"]
            assert action_box["x"] >= 0
            assert action_box["x"] + action_box["width"] <= width - 20
            assert page.locator('.header-url-actions [aria-label="Search Archive.org"]').is_visible()
            controls = page.locator(
                ".header-badges > .badge, .year-variants > summary, .selected-capture > summary",
            )
            for control in controls.all():
                if control.is_visible():
                    assert control.bounding_box()["height"] == 28
            toggle = page.get_by_role("button", name="Toggle saved outputs", exact=True)
            toggle_box = toggle.bounding_box()
            header_box = page.locator(".header-top").bounding_box()
            assert toggle_box["width"] == 20
            assert toggle_box["height"] == header_box["height"]
            assert toggle_box["x"] + toggle_box["width"] == width
            toggle.click()
            assert toggle.get_attribute("aria-expanded") == "false"
            assert not page.locator("#snapshot-output-browser").is_visible()
            toggle.click()
            assert toggle.get_attribute("aria-expanded") == "true"
            assert page.locator("#snapshot-output-browser").is_visible()
            page.locator(".header-top").click(position={"x": 2, "y": 2})
            assert toggle.get_attribute("aria-expanded") == "false", f"Navbar background did not collapse at {width}px"
            page.locator(".header-top").click(position={"x": 2, "y": 2})
            assert toggle.get_attribute("aria-expanded") == "true"
            year_menu = page.locator(".year-variants").first
            year_menu.locator("summary").click()
            assert year_menu.get_attribute("open") is not None
            assert toggle.get_attribute("aria-expanded") == "true"
            year_menu.locator("summary").click()
            page.locator(".output-stack-article_text").click()
            for file_list in page.locator(".other-files-preview > .loose-items").all():
                assert file_list.evaluate("e => getComputedStyle(e).overflowY") == "auto"
            stack = page.locator(".header-bottom")
            assert stack.evaluate("e => getComputedStyle(e).overflowY") == "visible"
            tray = page.locator("#stack-tray").bounding_box()
            frame = page.locator("#main-frame-wrapper").bounding_box()
            assert frame["y"] >= tray["y"] + tray["height"]
            assert frame["height"] >= height
            page.locator("#main-frame-wrapper").scroll_into_view_if_needed()
            assert page.evaluate("scrollY") > 0
            page.get_by_role("button", name="Collapse stack", exact=True).click()
        browser.close()


def test_ios_phone_header_keeps_actions_and_capture_date_on_one_row(snapshot, live_server):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright

    port = urlsplit(live_server.url).port
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html", wait_until="domcontentloaded")
        for native_app in (False, True):
            if native_app:
                # This is the marker the native WKWebView adds; CSS remains server-owned.
                page.evaluate(
                    "document.documentElement.classList.add('archivebox-native-app', 'archivebox-ios-app', 'archivebox-ios-phone')",
                )
            for width in (390, 320, 768) if native_app else (390, 320):
                page.set_viewport_size({"width": width, "height": 844})
                actions = page.locator(".header-url-actions").bounding_box()
                captures = page.locator(".header-capture-row").bounding_box()
                assert abs(actions["y"] - captures["y"]) < 1
                assert actions["x"] + actions["width"] <= captures["x"]
                assert captures["x"] + captures["width"] <= width
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        browser.close()


@pytest.mark.django_db(transaction=True)
def test_year_badges_attach_selected_capture_to_its_year(snapshot, live_server, tmp_path):
    from datetime import datetime, timezone
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.bookmarked_at = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
    snapshot.permissions = "public"
    snapshot.save(update_fields=["bookmarked_at", "permissions"])
    copies = [snapshot]
    for date in (datetime(2025, 3, 2, 12, tzinfo=timezone.utc), datetime(2026, 6, 1, 12, tzinfo=timezone.utc)):
        crawl = Crawl.objects.create(urls=snapshot.url, created_by=snapshot.crawl.created_by)
        copies.append(Snapshot.objects.create(url=snapshot.url, crawl=crawl, permissions="public", bookmarked_at=date))
    for copy in copies:
        save_output(copy, "defuddle")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"])
        page = browser.new_page()
        for selected, expected_year, expected_date in ((snapshot, "2026", "2026-09-23"), (copies[1], "2025", "2025-03-02")):
            page.goto(f"http://web.archivebox.localhost:{port}{selected.get_absolute_url()}/index.html", wait_until="domcontentloaded")
            assert page.locator(".capture-year").evaluate_all("nodes => nodes.map(e => e.dataset.year)") == ["2025", "2026"]
            assert [text.split() for text in page.locator(".year-label").all_text_contents()] == [["2025", "1"], ["2026", "2"]]
            group = page.locator(f'.capture-year[data-year="{expected_year}"]')
            assert group.locator(".header-date").inner_text() == expected_date
            assert group.locator("details").count() == 1
            assert page.locator(".header-date").count() == 1
            assert "CAPTURES" not in page.locator(".header-capture-row").inner_text().upper()
            for width, height in ((1440, 1000), (768, 1024), (390, 844), (320, 700)):
                page.set_viewport_size({"width": width, "height": height})
                year = group.locator(".year-label").bounding_box()
                date = group.locator(".header-date").bounding_box()
                assert abs(year["y"] - date["y"]) < 1
                assert abs(year["x"] + year["width"] - date["x"]) < 1
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(tmp_path / f"year-badges-{expected_year}-{width}.png"))
            menu = group.locator(".snapshot-variants-list")
            group.locator(".year-label").click()
            assert menu.is_visible()
            assert menu.locator("a").count() == 3
            assert menu.locator('[aria-current="page"]').count() == 1
            group.locator(".header-date").click()
            assert not menu.is_visible()
            group.locator(".header-date").click()
            assert menu.is_visible()
            assert menu.locator("a").count() == 3
            group.locator(".year-label").click()
            other_year = "2025" if expected_year == "2026" else "2026"
            other = page.locator(f'.capture-year[data-year="{other_year}"]')
            other.locator("summary").click()
            other_menu = other.locator(".snapshot-variants-list")
            assert other_menu.locator("a").count() == (1 if other_year == "2025" else 2)
            assert all(text.strip().startswith(other_year) for text in other_menu.locator("a").all_text_contents())
            assert other_menu.locator('[aria-current="page"]').count() == 0
        browser.close()
