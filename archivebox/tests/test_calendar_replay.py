"""Capture public calendars with the CLI and inspect their actual offline viewer."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from abx_plugins import get_plugins_dir
from playwright.sync_api import expect, sync_playwright

from .conftest import cli_env, get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process

W3C = "https://www.w3.org/events/meetings/f7fc20fd-5d9e-4427-94cd-34268db72ca8/"


def test_webcal_subscription_cli(initialized_archive, browser_runtime):
    """Accept a subscription URL actually published by Calendify's event page."""
    root = initialized_archive
    url = "webcal://calendify.com/session/K7NgQ1qGgL8/ical"
    env = cli_env(
        plugins_root=Path(os.environ.get("ABX_PLUGINS_DIR", str(get_plugins_dir()))),
        ABXPKG_LIB_DIR=str(browser_runtime["lib_dir"]),
        CHROME_BINARY=str(browser_runtime["chrome_binary"]),
        CHROME_HEADLESS="true",
        AUTH_STORAGE_FILE="",
    )
    captured = run_archivebox_cmd(["add", "--plugins=calendar", url], cwd=root, env=env, timeout=180)
    (root / "webcal-capture.log").write_text(captured.stdout + captured.stderr)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    listed = run_archivebox_cmd(["list", "--json"], cwd=root, env=env, timeout=30)
    assert listed.returncode == 0, listed.stderr
    snapshots, _ = json.JSONDecoder().raw_decode(listed.stdout.lstrip())
    assert len(snapshots) == 1, listed.stdout
    assert snapshots[0]["url"] == "https://calendify.com/session/K7NgQ1qGgL8/ical"
    output = Path(snapshots[0]["output_dir"]) / "calendar"
    manifest = json.loads((output / "downloads.json").read_text())
    assert len(manifest["files"]) == manifest["event_count"] == len(manifest["events"]) == 1
    assert manifest["events"][0]["summary"] == "Intro to the Decentralized Internet & Privacy devroom"
    item = manifest["files"][0]
    body = (output / item["path"]).read_bytes()
    assert body.startswith(b"BEGIN:VCALENDAR") and body.rstrip().endswith(b"END:VCALENDAR")
    assert len(body) == item["size"] > 0
    assert hashlib.sha256(body).hexdigest() == item["sha256"]


@pytest.mark.parametrize(
    ("url", "kind", "file_count"),
    [
        ("https://www.gov.uk/bank-holidays", "holidays", 3),
        (W3C + "export/", "series", 1),
        (W3C + "20260624T120000/export", "single", 1),
    ],
)
def test_calendar_capture_and_replay(url, kind, file_count, initialized_archive, browser_runtime):
    root = initialized_archive
    port = get_free_port()
    env = cli_env(
        plugins_root=Path(os.environ.get("ABX_PLUGINS_DIR", str(get_plugins_dir()))),
        ABXPKG_LIB_DIR=str(browser_runtime["lib_dir"]),
        CHROME_BINARY=str(browser_runtime["chrome_binary"]),
        CHROME_HEADLESS="true",
        AUTH_STORAGE_FILE="",
        BASE_URL=f"http://archivebox.localhost:{port}",
        BIND_ADDR=f"127.0.0.1:{port}",
    )
    captured = run_archivebox_cmd(["add", "--plugins=calendar", url], cwd=root, env=env, timeout=180)
    (root / "capture.log").write_text(captured.stdout + captured.stderr)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    listed = run_archivebox_cmd(["list", "--json"], cwd=root, env=env, timeout=30)
    assert listed.returncode == 0, listed.stderr
    snapshots, _ = json.JSONDecoder().raw_decode(listed.stdout.lstrip())
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    output = Path(snapshot["output_dir"]) / "calendar"
    manifest = json.loads((output / "downloads.json").read_text())
    assert len(manifest["files"]) == file_count
    for item in manifest["files"]:
        body = (output / item["path"]).read_bytes()
        assert body.startswith(b"BEGIN:VCALENDAR") and body.rstrip().endswith(b"END:VCALENDAR")
        assert len(body) == item["size"] > 0
        assert hashlib.sha256(body).hexdigest() == item["sha256"]

    server = start_archivebox_server(root, port=port, env=env, log_name="server.log")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page(viewport={"width": 1600, "height": 1000}, accept_downloads=True, locale="en-GB", timezone_id="UTC")
            page.goto(f"http://web.archivebox.localhost:{port}/public/")
            page.locator(f'a[href*="/web/"][href*="{snapshot["id"]}"]').first.click()
            page.get_by_role("button", name="Embedded media,", exact=False).click()
            card = page.locator('.thumb-card[data-plugin-name="calendar"]')
            expect(card).to_be_visible()
            card.locator('a[target="preview"]').first.click()
            preview = page.frame_locator("#main-frame")
            expect(preview.get_by_role("navigation", name="Calendar controls")).to_be_visible()
            expect(preview.locator("#notice")).to_contain_text("Original ICS files are complete.")
            expect(preview.locator("#file option")).to_have_count(file_count)
            date = preview.get_by_label("Go to month")
            date.fill("2026-12" if kind == "holidays" else "2024-12" if kind == "series" else "2026-06")
            date.press("Tab")
            if kind == "holidays":
                expect(preview.locator("#period")).to_have_text("December 2026")
                christmas = preview.locator('#month .day:has(> span:text-is("25"))').get_by_role(
                    "button",
                    name="All day · Christmas Day",
                    exact=True,
                )
                expect(christmas).to_have_count(1)
                expect(
                    preview.locator('#month .day:has(> span:text-is("26"))').get_by_role(
                        "button",
                        name="All day · Christmas Day",
                        exact=True,
                    ),
                ).to_have_count(0)
                christmas.click()
                expect(preview.get_by_role("heading", name="Christmas Day", exact=True)).to_be_visible()
                expect(preview.locator("#detail")).to_contain_text("2026-12-25 (all day)")
                expect(preview.locator("#detail")).to_contain_text("2026-12-26 (all day) (exclusive)")
            else:
                expect(preview.locator("#period")).to_have_text("December 2024" if kind == "series" else "June 2026")
                day = "25" if kind == "series" else "24"
                meeting = preview.locator(f'#month .day:has(> span:text-is("{day}"))').get_by_role(
                    "button",
                    name="12:00 · CSS weekly meeting",
                    exact=True,
                )
                expect(meeting).to_have_count(1)
                meeting.click()
                expect(preview.locator("#detail")).to_contain_text(
                    f"{'2024-12-25' if kind == 'series' else '2026-06-24'}T12:00:00 (America/New_York)",
                )
                expect(preview.locator("#detail")).to_contain_text("Zoom")
                expect(preview.get_by_role("link", name="W3C Calendar (mailto:noreply@w3.org)", exact=True)).to_be_visible()
                if kind == "series":
                    expect(meeting).to_have_class("event cancelled")
                    expect(preview.locator("#detail")).to_contain_text("CANCELLED")
                    for day in ("4", "11", "18"):
                        expect(
                            preview.locator(f'#month .day:has(> span:text-is("{day}"))').get_by_role(
                                "button",
                                name="12:00 · CSS weekly meeting",
                                exact=True,
                            ),
                        ).to_have_count(1)
                    # This genuine W3C exception moves the July 2026 meeting
                    # into July 2010, before its master's first occurrence.
                    date.fill("2010-07")
                    date.press("Tab")
                    moved = preview.locator('#month .day:has(> span:text-is("1"))').get_by_role(
                        "button",
                        name="12:00 · CSS weekly meeting",
                        exact=True,
                    )
                    expect(moved).to_have_count(1)
                    moved.click()
                    expect(preview.locator("#detail")).to_contain_text("2010-07-01T12:00:00 (America/New_York)")
                    expect(preview.locator("#detail")).to_contain_text("2010-07-01T12:01:00 (America/New_York)")
                    date.fill("2024-12")
                    date.press("Tab")
            page.get_by_role("button", name="Toggle saved outputs", exact=True).click()
            page.locator("body").press("Control+Home")
            page.screenshot(path=str(root / f"calendar-{kind}-month.png"))
            preview.get_by_role("button", name="Agenda", exact=True).click()
            expect(preview.locator("#agenda")).to_be_visible()
            expect(preview.locator("#month")).to_be_hidden()
            expect(preview.locator("#agenda .event")).to_have_count(2 if kind == "holidays" else 4 if kind == "series" else 1)
            for item in manifest["files"]:
                preview.locator("#file").select_option(item["path"])
                expect(preview.locator("#download")).to_have_attribute("download", item["filename"])
                with page.expect_download() as original:
                    preview.get_by_role("link", name="Download ICS", exact=True).click()
                assert original.value.failure() is None
                assert Path(original.value.path()).read_bytes() == (output / item["path"]).read_bytes()
            page.screenshot(path=str(root / f"calendar-{kind}.png"))
            if kind == "holidays":
                preview.get_by_role("button", name="Month", exact=True).click()
                page.set_viewport_size({"width": 390, "height": 844})
                expect(preview.locator("#month")).to_be_visible()
                widths = preview.locator("body").evaluate(
                    "() => ({scroll: document.documentElement.scrollWidth, viewport: window.innerWidth})",
                )
                assert widths["scroll"] <= widths["viewport"]
                page.screenshot(path=str(root / "calendar-holidays-mobile.png"))
            browser.close()
    finally:
        stop_archivebox_process(server)
