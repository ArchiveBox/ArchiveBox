"""Full plugin viewers load only the sibling manifests they render."""

import pytest
from django.db import connection
from django.template import Context
from django.test.utils import CaptureQueriesContext
from django.utils.html import escapejs

from archivebox.core.models import ArchiveResult
from archivebox.core.templatetags.core_tags import plugin_full

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("plugin", "source"),
    [
        ("gallerydl", "gallerydl"),
        ("git", "wget"),
        ("liteparse", "wget"),
        ("responses", "responses"),
        ("seo", "favicon"),
        ("ytdlp", "ytdlp"),
    ],
)
def test_full_viewer_selects_only_needed_manifests(snapshot, plugin, source):
    results = {}
    for name in (
        "gallerydl",
        "git",
        "dom",
        "singlefile",
        "liteparse",
        "wget",
        "staticfile",
        "papersdl",
        "responses",
        "seo",
        "favicon",
        "ytdlp",
        "archivewebpage",
    ):
        results[name] = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin=name,
            status="succeeded",
            output_str="index.html",
            output_files={
                f"{name}/asset-{index}.html": {"size": index, "mimetype": "text/html", "root_relative": True} for index in range(128)
            },
        )
    with CaptureQueriesContext(connection) as queries:
        rendered = plugin_full(Context({}), results[plugin])
    manifest_queries = [query["sql"] for query in queries if '"core_archiveresult"' in query["sql"] and '"output_files"' in query["sql"]]
    assert len(manifest_queries) == 1, manifest_queries
    assert '"plugin" IN (' in manifest_queries[0]
    assert '"output_str"' not in manifest_queries[0].split(" FROM ")[0]
    assert escapejs(f"{source}/asset-127.html") in rendered
    assert escapejs("archivewebpage/asset-") not in rendered


@pytest.mark.django_db(transaction=True)
def test_full_viewers_render_saved_sibling_files(snapshot, live_server, browser_runtime):
    import json
    from pathlib import Path
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    image = (Path(__file__).parents[2] / "publicsite/assets/social-card.png").read_bytes()
    source_name = "capture-source-" * 8 + ".png"
    outputs = {
        "gallerydl": {"example.png": image},
        "responses": {
            f"all/{source_name}": image,
            "index.jsonl": json.dumps({"path": f"all/{source_name}", "url": f"https://example.com/{source_name}"}).encode(),
        },
        # The hook truncates output stems to 96 characters, losing the original
        # extension. File-type filters must use the resolved source metadata.
        "liteparse": {f"{source_name[:96]}.txt": f"<!-- source: {source_name} -->\nArchived image transcription".encode()},
        "seo": {
            "seo.json": json.dumps(
                {"url": "https://example.com/", "og:title": "Saved social title", "og:description": "Saved social description"},
            ).encode(),
        },
        "favicon": {"favicon.png": image},
        "git": {"README.md": b"# Saved repository\n\nRepository contents."},
        "wget": {
            "index.html": b'<html><head><meta name="description" content="Saved repository description"></head><body>Repository</body></html>',
        },
        "ytdlp": {"clip.info.json": json.dumps({"title": "Saved media title", "uploader": "Saved creator"}).encode()},
    }
    for plugin, files in outputs.items():
        metadata = {}
        for name, content in files.items():
            path = snapshot.output_dir / plugin / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            metadata[name] = {"size": len(content), "mimetype": "image/png" if name.endswith(".png") else "text/plain"}
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin=plugin,
            status="succeeded",
            output_str=next(iter(files)),
            output_files=metadata,
        )
    origin = f"http://{get_snapshot_host(snapshot.archive_path_from_db)}"
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        for plugin in ("gallerydl", "responses", "liteparse", "seo", "git", "ytdlp"):
            response = page.goto(f"{origin}/{plugin}/{next(iter(outputs[plugin]))}?preview=1")
            assert response.status == 200
            if plugin in {"gallerydl", "responses", "liteparse"}:
                expect(page.locator("#gallery .tile")).to_have_count(1)
                page.wait_for_function("document.querySelector('#gallery img')?.naturalWidth > 0")
                if plugin == "gallerydl":
                    page.locator("#gallery .tile > a").click()
                    expect(page.locator("#viewer")).to_be_visible()
                    expect(page.locator("#viewer-name")).to_have_text("example.png")
                elif plugin == "liteparse":
                    expect(page.locator(".text-preview")).to_have_text("Archived image transcription")
                    page.get_by_role("button", name="Images 1", exact=True).click()
                    expect(page.locator("#gallery .tile:visible")).to_have_count(1)
                    page.get_by_role("button", name="Documents 0", exact=True).click()
                    expect(page.locator("#gallery .tile:visible")).to_have_count(0)
                    expect(page.locator("#count")).to_have_text("0 / 1")
                    page.get_by_role("button", name="All 1", exact=True).click()
                    expect(page.locator("#gallery .tile:visible")).to_have_count(1)
            elif plugin == "seo":
                expect(page.locator(".link-copy")).to_contain_text("Saved social title")
                page.wait_for_function("document.querySelector('.site-icon')?.naturalWidth > 0")
            elif plugin == "git":
                expect(page.locator("#entries")).to_contain_text("README.md")
                expect(page.locator("#description")).to_have_text("Saved repository description")
                expect(page.locator("#readme iframe").content_frame.locator("body")).to_contain_text("Saved repository")
            else:
                expect(page.locator("#title")).to_have_text("Saved media title")
                expect(page.locator("#byline")).to_contain_text("Saved creator")
                expect(page.locator("#count")).to_contain_text("1 item")
            assert errors == [], (plugin, errors)
        browser.close()
