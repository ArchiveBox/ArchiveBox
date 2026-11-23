import pytest

from archivebox.crawls.models import Crawl
from archivebox.tests.test_cli_add_1 import write_import_format_files


@pytest.mark.django_db(transaction=True)
def test_archivebox_exports_roundtrip_through_add(initialized_archive, browser_runtime, tmp_path, admin_user, httpserver):
    from datetime import datetime, timezone
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.exports import write_snapshot_metadata
    from archivebox.core.models import Snapshot, Tag
    from archivebox.tests.conftest import (
        cli_env,
        create_admin_and_token,
        get_free_port,
        run_queued_crawls,
        start_archivebox_server,
        stop_server,
    )
    from archivebox.tests.test_orm_helpers import use_archivebox_db
    from archivebox.tests.test_ui_add_view_runtime import _stop_worker

    originals = []
    source_crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    for index, path in enumerate(("/Research/", "/a,b", "/quoted")):
        httpserver.expect_request(path).respond_with_data("Imported page", content_type="text/plain")
        snapshot = Snapshot.objects.create(
            crawl=source_crawl,
            url=httpserver.url_for(path).replace("localhost", "127.0.0.1"),
            title=f'Research {index}, "quoted"\nsecond line',
            bookmarked_at=datetime(2020, 1, index + 1, 12, 34, 56, 123456, tzinfo=timezone.utc),
        )
        names = [f"topic-{index}", "reading list", 'quotes "preserved"']
        snapshot.tags.set([Tag.objects.get_or_create(name=name)[0] for name in names])
        originals.append({"url": snapshot.url, "title": snapshot.title, "bookmarked_at": snapshot.bookmarked_at, "tags": set(names)})
    files = []
    for format in ("csv", "jsonl"):
        source = tmp_path / f"snapshots.{format}"
        with source.open("w", newline="") as output:
            write_snapshot_metadata(Snapshot.objects.filter(crawl=source_crawl), format, output)
        files.append(source)
    port = get_free_port()
    env = cli_env(server=True, port=port, PLUGINS="parse_jsonl_urls,parse_txt_urls", ONLY_NEW="False", URL_DENYLIST="")
    create_admin_and_token(initialized_archive)
    try:
        start_archivebox_server(initialized_archive, port=port, env=env)
        _stop_worker(initialized_archive, "worker_runner")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            try:
                page = browser.new_page()
                base = f"http://admin.archivebox.localhost:{port}"
                page.goto(f"{base}/admin/login/?next=/add/")
                page.locator('[name="username"]').fill("apitestadmin")
                page.locator('[name="password"]').fill("testpass123")
                page.get_by_role("button", name="Log in", exact=True).click()
                for source in files:
                    page.goto(base + "/add/")
                    with page.expect_file_chooser() as chooser:
                        page.get_by_role("button", name="Upload", exact=True).click()
                    chooser.value.set_files(source)
                    expect(page.locator(".detected-url-value")).to_have_text([item["url"] for item in originals])
                    page.locator("#id_url_filters_only_new").uncheck()
                    page.locator("#submit").click()
                    page.wait_for_url("**/admin/crawls/crawl/*/change/")
            finally:
                browser.close()
    finally:
        stop_server(initialized_archive)
    run_queued_crawls(initialized_archive, env=env)
    with use_archivebox_db(initialized_archive):
        assert Crawl.objects.count() == len(files)
        for crawl in Crawl.objects.all():
            assert crawl.snapshot_set.count() == len(originals)
            for original in originals:
                snapshot = crawl.snapshot_set.get(url=original["url"])
                assert snapshot.title == original["title"]
                assert snapshot.bookmarked_at == original["bookmarked_at"]
                assert set(snapshot.tags.values_list("name", flat=True)) == original["tags"]


@pytest.mark.django_db(transaction=True)
def test_large_csv_upload_preserves_full_input(live_server, admin_user, browser_runtime, settings, tmp_path):
    from time import perf_counter
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.exports import write_snapshot_metadata
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine

    base = f"http://archivebox.localhost:{urlsplit(live_server.url).port}"
    settings.CONFIG = settings.CONFIG.model_copy(update={"BASE_URL": base})
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": base}
    machine.save(update_fields=["config"])
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    Snapshot.objects.bulk_create(
        [
            Snapshot(crawl=crawl, url=f"https://example.com/{i:05}", title="CSV export " + "x" * 400, timestamp=str(1900600000 + i))
            for i in range(24000)
        ],
    )
    source = tmp_path / "snapshots.csv"
    with source.open("w") as output:
        write_snapshot_metadata(Snapshot.objects.filter(crawl=crawl), "csv", output)
    assert source.stat().st_size >= 12_000_000
    text = source.read_text()
    admin_url = base.replace("//archivebox", "//admin.archivebox")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            page = browser.new_page()
            page.goto(f"{admin_url}/admin/login/?next=/admin/crawls/crawl/")
            page.locator('[name="username"]').fill(admin_user.username)
            page.locator('[name="password"]').fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            with page.expect_file_chooser() as chooser:
                page.get_by_role("button", name="Upload file", exact=True).click()
            started = perf_counter()
            chooser.value.set_files(source)
            page.wait_for_url("**/add/")
            expect(page.locator("#url-upload-status")).to_have_text("File text added.")
            expect(page.locator(".detected-url-item")).to_have_count(100)
            expect(page.locator("#detected-urls-summary")).to_have_text(">100 total")
            elapsed = perf_counter() - started
            print(f"CSV upload: {source.stat().st_size:,} bytes, {elapsed:.2f}s to preview")
            assert elapsed < 5, f"Large CSV preview took {elapsed:.2f}s"
            assert page.locator("#id_url").input_value() == text
            assert page.locator(".detected-url-item").count() <= 100
            page.locator("#submit").click()
            page.wait_for_url("**/admin/crawls/crawl/*/change/")
        finally:
            browser.close()
    imported = Crawl.objects.exclude(pk=crawl.pk).get()
    assert imported.urls.replace("\r\n", "\n") == text
    assert "https://example.com/23999" in imported.urls


@pytest.mark.django_db(transaction=True)
def test_upload_browser_and_native_parser(initialized_archive, browser_runtime, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.tests.conftest import (
        cli_env,
        create_admin_and_token,
        get_free_port,
        run_queued_crawls,
        start_archivebox_server,
        stop_server,
    )
    from archivebox.tests.test_cli_add_1 import IMPORT_FORMAT_ENV, IMPORT_FORMAT_EXPECTATIONS, assert_expected_import_snapshots
    from archivebox.tests.test_orm_helpers import use_archivebox_db
    from archivebox.tests.test_ui_add_view_runtime import _stop_worker

    files = write_import_format_files(tmp_path)
    port = get_free_port()
    env = cli_env(server=True, port=port, **IMPORT_FORMAT_ENV)
    create_admin_and_token(initialized_archive)
    try:
        start_archivebox_server(initialized_archive, port=port, env=env)
        _stop_worker(initialized_archive, "worker_runner")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(browser_runtime["chrome_binary"]),
                args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
            )
            try:
                page = browser.new_page()
                base = f"http://admin.archivebox.localhost:{port}"
                page.goto(f"{base}/admin/login/?next=/admin/crawls/crawl/")
                page.locator('[name="username"]').fill("apitestadmin")
                page.locator('[name="password"]').fill("testpass123")
                page.get_by_role("button", name="Log in", exact=True).click()
                for index, source in enumerate(files.values()):
                    list_path = "/admin/core/snapshot/" if index % 2 else "/admin/crawls/crawl/"
                    page.goto(base + list_path)
                    expect(page.locator("#crawl-drop-overlay")).to_be_hidden()
                    with page.expect_file_chooser() as chooser:
                        page.get_by_role("button", name="Upload file", exact=True).click()
                    chooser.value.set_files(source)
                    page.wait_for_url("**/add/")
                    expect(page.locator("#id_url")).to_have_value(source.read_text())
                    expect(page.locator("#url-counter")).not_to_have_text("0 URLs detected")
                    page.locator("#submit").click()
                    page.wait_for_url("**/admin/crawls/crawl/*/change/")
                    expect(page.locator("#id_urls")).to_have_value(source.read_text())
                # Multiple files follow the same existing /add/ import queue.
                page.goto(base + "/admin/core/snapshot/")
                with page.expect_file_chooser() as chooser:
                    page.get_by_role("button", name="Upload file", exact=True).click()
                chooser.value.set_files([files["rss"], files["netscape"]])
                page.wait_for_url("**/add/")
                expect(page.locator("#id_url")).to_have_value(files["rss"].read_text() + files["netscape"].read_text())
                page.reload()
                expect(page.locator("#id_url")).to_have_value("")
                page.go_back()
                expect(page.locator("#crawl-drop-overlay")).to_be_hidden()
                with page.expect_file_chooser() as chooser:
                    page.get_by_role("button", name="Upload file", exact=True).click()
                chooser.value.set_files(files["txt"])
                page.wait_for_url("**/add/")
                expect(page.locator("#id_url")).to_have_value(files["txt"].read_text())
                # Drag actual selected text with native mouse events, without
                # dispatching synthetic drop events or replacing a handler.
                page.goto(base + "/admin/crawls/crawl/add/")
                text = page.locator("#id_urls")
                text.fill("https://example.com/dropped-text")
                text.select_text()
                box = text.bounding_box()
                page.mouse.move(box["x"] + 35, box["y"] + 22)
                page.mouse.down()
                # Native text dragging requires a held press; moving at once
                # starts a new text selection on macOS.
                page.wait_for_timeout(200)
                page.mouse.move(box["x"] + 80, box["y"] + 22, steps=10)
                page.mouse.move(500, 90, steps=20)
                page.screenshot(path=str(tmp_path / "drop-overlay.png"))
                expect(page.locator("#crawl-drop-overlay")).to_be_visible()
                expect(page.locator("#crawl-drop-title")).to_have_text("Drop to create a crawl")
                page.mouse.up()
                page.wait_for_url("**/add/")
                expect(page.locator("#id_url")).to_have_value("https://example.com/dropped-text")
                page.locator("#submit").click()
                page.wait_for_url("**/admin/crawls/crawl/*/change/")
                expect(page.locator("#id_urls")).to_have_value("https://example.com/dropped-text")
            finally:
                browser.close()
    finally:
        stop_server(initialized_archive)

    run_queued_crawls(initialized_archive, env=env, timeout=240)
    assert_expected_import_snapshots(initialized_archive, {case["url"] for case in IMPORT_FORMAT_EXPECTATIONS.values()})
    with use_archivebox_db(initialized_archive):
        assert Crawl.objects.count() == 7
        for name, case in IMPORT_FORMAT_EXPECTATIONS.items():
            # Native HTML form submission normalizes textarea newlines to CRLF.
            crawl = Crawl.objects.get(urls=files[name].read_text().replace("\n", "\r\n"))
            snapshot = crawl.snapshot_set.get(url=case["url"])
            assert snapshot.depth == 0
            if "title" in case:
                assert snapshot.title == case["title"]
                assert snapshot.bookmarked_at.date().isoformat() == case["date"]
                assert case["tags"].issubset(set(snapshot.tags.values_list("name", flat=True)))
        assert Crawl.objects.get(urls="https://example.com/dropped-text").snapshot_set.get().url == "https://example.com/dropped-text"
