"""Shared Chrome lifecycle outputs retain their own viewer and raw bytes."""

from urllib.parse import urlsplit
import pytest


@pytest.mark.django_db(transaction=True)
def test_chrome_lifecycle_preview(snapshot, live_server, browser_runtime):
    import json
    from playwright.sync_api import sync_playwright, expect
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Machine
    from archivebox.core.routes_util import get_snapshot_host

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.status = "sealed"
    snapshot.save(update_fields=["permissions", "status"])
    folder = snapshot.output_dir / "chrome"
    folder.mkdir(parents=True, exist_ok=True)
    bodies = {
        "navigation.json": json.dumps({"url": snapshot.url, "finalUrl": snapshot.url, "status": 200}),
        "frame_loads.json": '{"frames": []}',
        "diagnostic.json": '{"diagnostic": true}',
    }
    for name, body in bodies.items():
        (folder / name).write_text(body)
    manifest = {name: {"size": len(body), "mimetype": "application/json"} for name, body in bodies.items()}
    # Actual queryset order determines the first lifecycle row, making the
    # shared-manifest ambiguity deterministic without replacing query behavior.
    rows = [
        ArchiveResult.objects.create(snapshot=snapshot, plugin="chrome", hook_name=hook, status="succeeded", output_files=manifest)
        for hook in ("on_Snapshot__01_chrome_tab", "on_Snapshot__02_chrome_navigate")
    ]
    ordered = list(ArchiveResult.objects.filter(pk__in=[row.pk for row in rows]))
    for row, path in zip(ordered, ("chrome/navigation.json", "chrome/frame_loads.json")):
        row.output_str = path
        row.save(update_fields=["output_str"])
    host = get_snapshot_host(str(snapshot.pk)).split(":")[0]
    origin = f"http://{host}:{port}"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        response = page.goto(f"{origin}/chrome/frame_loads.json?preview=1")
        assert response.status == 200
        expect(page.get_by_role("heading", name="Capture timeline", exact=True)).to_be_visible()
        raw = page.goto(f"{origin}/chrome/frame_loads.json?raw=1")
        assert raw.status == 200 and raw.text() == bodies["frame_loads.json"]
        helper = page.goto(f"{origin}/chrome/diagnostic.json?preview=1")
        assert helper.status == 200
        assert page.get_by_role("heading", name="Capture timeline", exact=True).count() == 0
        browser.close()
