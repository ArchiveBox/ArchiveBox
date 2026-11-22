"""The live screenshot group must launch its real capture just in time."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_live_capture_starts_when_its_view_is_dequeued():
    script = (ROOT / "bin/collect_ui_screenshots.sh").read_text()
    subprocess.run(["bash", "-n", str(ROOT / "bin/collect_ui_screenshots.sh")], check=True)
    dequeue = script.index("IFS='|' read -r name url expected_path source capture_mode")
    launch = script.index('(run_gallery_add "" "$EXAMPLE_URL")', dequeue)
    pid = script.index("ARCHIVE_PID=$!", launch)
    guard = script.index('if [[ "$capture_mode" == "live-progress" ]]; then', dequeue)
    start = script.index("EXAMPLE_CAPTURE_STARTED_AT=", dequeue)
    announce = script.index('echo "[*] $name: $url"', dequeue)
    assert dequeue < guard < start < launch < pid < announce
    assert script[launch:pid].rstrip().endswith("&")
    helper_start = script.index("run_gallery_add() {")
    helper = script[helper_start : script.index("\n}", helper_start)]
    assert 'exec uv run --no-cache --project "$REPO_DIR" "$REPO_DIR/bin/generate_ui_screenshot_gallery.py"' in helper
    assert 'capture-add "$PLUGIN_SCREENSHOT_PLAN" "$SCOPED_GALLERY_OPT_INS" "$plugin_names" "$source_url"' in helper
    assert script.count("EXAMPLE_CAPTURE_STARTED_AT=") == 1
    assert "Snapshot View (capture in progress)|||archivebox/templates/core/snapshot.html|live-progress" in script
    assert 'url="$LIVE_SNAPSHOT_VIEW_URL"' in script[launch:announce]
    assert 'expected_path="$LIVE_SNAPSHOT_VIEW_PATH"' in script[launch:announce]
    assert 'if ! wait "$ARCHIVE_PID"; then' in script[announce:]


def test_every_live_viewport_keeps_the_same_real_progress_gate():
    screenshot = (ROOT / "bin/take_screenshot.js").read_text()
    capture = screenshot[screenshot.index("const capture = async") : screenshot.index("if (variants.length)")]
    assert "waitForLiveProgress(page, liveProgressDeadline, screencastResponses)" in capture
    assert capture.index("waitForLiveProgress(") < capture.index("await page.screenshot(")
    assert "const liveProgressDeadline = Date.now() + 60000;" in screenshot
    assert "await capture(variantPath)" in screenshot[screenshot.index("if (variants.length)") :]
