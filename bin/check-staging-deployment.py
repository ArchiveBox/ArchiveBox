#!/usr/bin/env python3
"""Exercise the automatically deployed candidate; never deploy it ourselves."""

import json
import hashlib
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import expect, sync_playwright


def main():
    target = os.environ["STAGING_TARGET"]
    sha = os.environ["STAGING_SHA"]
    host, port = {"cabbage": ("100.66.141.33", "44"), "digestbox": ("146.190.134.33", "22")}[target]
    evidence = Path("staging-evidence")
    evidence.mkdir(exist_ok=True)
    ssh = [
        "ssh",
        "-F",
        "/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={os.environ['STAGING_KNOWN_HOSTS_FILE']}",
        "-o",
        "ConnectTimeout=15",
        "-i",
        os.environ["STAGING_KEY_FILE"],
        "-p",
        port,
        f"root@{host}",
    ]
    deadline = time.monotonic() + 90 * 60
    inspection = None
    expected_pins = {
        p["name"]: p["version"]
        for p in tomllib.loads(Path("uv.lock").read_text())["package"]
        if p["name"] in {"abx-dl", "abx-plugins", "abxbus", "abxpkg"}
    }

    def remote(operation):
        return subprocess.run([*ssh, f"{operation} {sha}"], text=True, capture_output=True, timeout=180)

    while time.monotonic() < deadline:
        check = remote("inspect")
        (evidence / "inspection.log").write_text(f"exit_code={check.returncode}\n{check.stdout}{check.stderr}")
        if check.returncode == 75 and inspection is None:
            # Deployment is asynchronous; this is observation, not a test retry
            # or permission to pull/restart a container from CI.
            print(check.stderr.strip(), flush=True)
            time.sleep(30)
            continue
        if check.returncode:
            raise RuntimeError(f"Staging inspection failed (exit {check.returncode}): {check.stderr or check.stdout}")
        current = json.loads(check.stdout)
        if current["helper_sha256"] != hashlib.sha256(Path("bin/staging-acceptance-host.sh").read_bytes()).hexdigest():
            raise RuntimeError("Staging host acceptance helper differs from the reviewed candidate")
        if not isinstance(current.get("abx_dl_image"), str) or not re.search(r"@sha256:[0-9a-f]{64}$", current["abx_dl_image"]):
            raise RuntimeError("Staging host did not report a digest-pinned abx-dl base image")
        if inspection is not None and current != inspection:
            raise RuntimeError("The deployed container changed during acceptance")
        inspection = current
        result = remote("capture")
        (evidence / "capture.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        report = json.loads(
            next(line.removeprefix("STAGING_REPORT=") for line in result.stdout.splitlines() if line.startswith("STAGING_REPORT=")),
        )
        (evidence / "capture.json").write_text(json.dumps(report, indent=2))
        if report["pins"] != expected_pins:
            raise RuntimeError(f"Deployed dependency pins differ: {report['pins']} != {expected_pins}")
        print(f"{target}: {report['status']}, crawl {report['crawl_id']}", flush=True)
        if report["status"] == "failed":
            raise RuntimeError("\n".join(report["errors"]))
        if report["status"] == "passed":
            break
        time.sleep(30)
    else:
        raise RuntimeError("Automatic deployment/capture did not complete within the acceptance window")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["CHROME_BINARY"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        for snapshot in report["snapshots"]:
            response = page.goto(snapshot["replay_url"], wait_until="domcontentloaded")
            assert response and response.ok, snapshot["replay_url"]
            page.locator('.thumb-card[data-plugin-name="screenshot"]').wait_for(state="attached")
            try:
                # The shell creates an about:blank iframe before replay starts.
                # Its presence previously accepted blank screenshots as proof of
                # replay. Exercise the default viewer and its real captured page,
                # using the same readiness contract as the WACZ browser tests.
                expect(page.locator(".header-title-text")).to_contain_text(re.compile(r"\S"))
                preview = page.locator("#main-frame")
                expect(preview).to_have_attribute("src", re.compile(r"/archivewebpage/archivewebpage\.wacz\?preview=1"))
                replay_root = preview.content_frame.locator("#replay-root")
                expect(replay_root).to_have_attribute("data-url", snapshot["url"])
                preview_frame = preview.element_handle().content_frame()
                assert preview_frame is not None
                preview_frame.wait_for_function(
                    """() => {
                        if (window.archiveboxReplayError) throw new Error(window.archiveboxReplayError);
                        return Boolean(window.archiveboxReplayReady);
                    }""",
                )
                # Extracted display titles need not match the captured document's
                # <title>: HedgeDoc's note heading and HTML title differ. Identify
                # the archived document by its replay origin/path and original URL,
                # as the ArchiveWebpage browser tests do. Wrapper frames and other
                # output thumbnails cannot satisfy this check.
                replay_base = replay_root.get_attribute("data-replaybase")
                assert replay_base
                replay_prefix = urljoin(preview_frame.url, f"{replay_base}w/")
                frames = list(preview_frame.child_frames)
                frame_titles = {}
                while frames:
                    replay = frames.pop()
                    frame_titles[replay.url] = replay.title().strip()
                    if replay.url.startswith(replay_prefix) and replay.url.endswith(f"/{snapshot['url']}"):
                        body = replay.locator("body")
                        expect(body).to_be_visible()
                        # Both acceptance URLs contain substantial article/profile
                        # text. Reject a blank frame or a short viewer error message.
                        assert len(" ".join(body.inner_text().split())) > 1000, f"Missing captured page content: {replay.url}"
                        break
                    frames.extend(replay.child_frames)
                else:
                    raise AssertionError(f"Captured URL {snapshot['url']!r} not found in replay frames: {frame_titles}")
            finally:
                page.screenshot(path=str(evidence / f"{snapshot['id']}.png"), full_page=True)
        browser.close()
    # Recheck identity and host OOM history after the browser flow too.
    final = remote("capture")
    if final.returncode:
        raise RuntimeError(final.stderr)
    final_report = json.loads(
        next(line.removeprefix("STAGING_REPORT=") for line in final.stdout.splitlines() if line.startswith("STAGING_REPORT=")),
    )
    final_inspection = remote("inspect")
    if final_report != report or final_inspection.returncode or json.loads(final_inspection.stdout) != inspection:
        raise RuntimeError("Deployment or capture evidence changed during the browser acceptance flow")
    fingerprint = subprocess.check_output([sys.executable, "bin/release-source-fingerprint.py", sha], text=True).strip()
    payload = {"acceptance_version": 1, "source_fingerprint": fingerprint, "run_id": os.environ["GITHUB_RUN_ID"], "inspection": inspection}
    request = {
        "ref": sha,
        "environment": target,
        "auto_merge": False,
        "required_contexts": [],
        "production_environment": False,
        "payload": payload,
        "description": "Real deployed capture, output and browser acceptance",
    }
    repository = os.environ["GITHUB_REPOSITORY"]
    deployment = json.loads(
        subprocess.check_output(["gh", "api", f"repos/{repository}/deployments", "--input", "-"], input=json.dumps(request), text=True),
    )
    subprocess.run(
        ["gh", "api", f"repos/{repository}/deployments/{deployment['id']}/statuses", "--input", "-"],
        input=json.dumps(
            {
                "state": "success",
                "auto_inactive": False,
                "log_url": f"https://github.com/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
            },
        ),
        text=True,
        check=True,
    )


if __name__ == "__main__":
    main()
