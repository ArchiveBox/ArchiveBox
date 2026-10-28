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
from urllib.parse import urljoin, urlsplit, urlunsplit

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
    health_only = os.environ.get("STAGING_HEALTH_ONLY") == "true"
    deadline = time.monotonic() + (10 if health_only else 90) * 60
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
        if inspection is None and (
            check.returncode == 75
            or (check.returncode == 1 and re.fullmatch(r"error: no such object: [\w.-]+\s*", check.stderr, re.IGNORECASE))
        ):
            # Deployment is asynchronous; this is observation, not a test retry
            # or permission to pull/restart a container from CI.
            # Watchtower briefly removes the old container before creating its
            # replacement. After acceptance starts, any disappearance still fails.
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
        if health_only:
            print(f"{target}: exact candidate {sha} deployed and healthy", flush=True)
            return
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
        browser_messages = []

        def record_browser_message(message, source):
            if len(browser_messages) >= 20:
                return
            text = message.text if hasattr(message, "text") else str(message)
            text = re.sub(r"https?://[^\s\"'<>]+", lambda match: safe_url(match.group(0)), text)
            browser_messages.append({"source": source, "message": text[:300]})

        def record_console(message):
            if message.type == "error":
                record_browser_message(message, "console")

        def record_page_error(error):
            record_browser_message(error, "pageerror")

        def safe_url(value):
            parts = urlsplit(value)
            if parts.scheme and not parts.netloc:
                return f"{parts.scheme}:<opaque>"
            if not parts.netloc:
                return urlunsplit(("", "", parts.path[:300], "", ""))
            return urlunsplit((parts.scheme, parts.netloc, parts.path[:300], "", ""))

        page.on("console", record_console)
        page.on("pageerror", record_page_error)
        for snapshot in report["snapshots"]:
            browser_messages.clear()
            response = page.goto(snapshot["replay_url"], wait_until="domcontentloaded")
            assert response and response.ok, snapshot["replay_url"]
            page.locator('.thumb-card[data-plugin-name="screenshot"]').wait_for(state="attached")
            try:
                # The shell creates an about:blank iframe before replay starts.
                # Its presence previously accepted blank screenshots as proof of
                # replay. Exercise the default viewer and its real captured page,
                # using the same readiness contract as the WACZ browser tests.
                expect(page.locator(".header-title-text")).to_contain_text(re.compile(r"\S"))
                # The default viewer keeps useful saved HTML in front while WACZ
                # loads. Observe the same replay context before/after promotion;
                # requiring it in main-frame first bypassed the readiness wait.
                preview = page.locator('#main-frame[src*="/archivewebpage/"], #replay-preload[src*="/archivewebpage/"]')
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
                expect(page.locator("#main-frame")).to_have_attribute("data-replay-painted", "1")
                expect(page.locator("#main-frame")).to_have_attribute("src", re.compile(r"/archivewebpage/archivewebpage\.wacz\?preview=1"))
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
            except BaseException:
                # Keep failure evidence bounded and avoid recording URL query
                # values, which may contain private capture parameters.
                try:
                    diagnostics = page.evaluate(
                        """() => ({
                            iframes: [...document.querySelectorAll('iframe')].slice(0, 10).map(frame => ({
                                id: frame.id.slice(0, 100),
                                src: frame.getAttribute('src') || '',
                                replayPainted: frame.dataset.replayPainted || '',
                            })),
                        })""",
                    )
                    diagnostics["iframes"] = [{**frame, "src": safe_url(frame["src"])} for frame in diagnostics["iframes"]]
                    diagnostics["frames"] = []
                    for frame in page.frames[:10]:
                        entry = {"name": frame.name[:100], "url": safe_url(frame.url)}
                        try:
                            entry.update(
                                frame.evaluate(
                                    """() => ({
                                        readyState: document.readyState,
                                        replayRoot: (() => {
                                            const root = document.querySelector('#replay-root');
                                            return root ? {present: true, dataUrl: root.dataset.url || '', dataReplaybase: root.dataset.replaybase || ''} : {present: false};
                                        })(),
                                    })""",
                                ),
                            )
                            entry["replayRoot"]["dataUrl"] = safe_url(entry["replayRoot"].get("dataUrl", ""))
                            entry["replayRoot"]["dataReplaybase"] = entry["replayRoot"].get("dataReplaybase", "")[:200]
                        except BaseException as error:
                            entry["inspectionError"] = str(error)[:200]
                        diagnostics["frames"].append(entry)
                    diagnostics["browserErrors"] = browser_messages
                    (evidence / f"{snapshot['id']}-browser-diagnostic.json").write_text(
                        json.dumps(diagnostics, indent=2),
                    )
                except BaseException as error:
                    print(f"Could not collect bounded browser diagnostics: {str(error)[:200]}", file=sys.stderr)
                try:
                    page.screenshot(path=str(evidence / f"{snapshot['id']}.png"), full_page=True)
                except BaseException:
                    pass
                raise
            else:
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
