"""Gallery capture waits for real lazy card documents and decoded pixels."""

import json
import os
import subprocess
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from archivebox.core.models import ArchiveResult
from archivebox.machine.models import Machine
from archivebox.tests.conftest import REPO_ROOT
from archivebox.tests.test_snapshot_output_stacks import save_output, save_response_image


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("selection", ["automatic", "manual", "unsupported", "explicit"])
def test_gallery_keeps_static_preview_until_real_replay_is_ready(snapshot, live_server, browser_runtime, tmp_path, selection):
    port = urlsplit(live_server.url).port
    hostname = "archivebox.test" if selection == "unsupported" else "archivebox.localhost"
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://{hostname}:{port}",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.url = "https://drive.google.com/drive/folders/1KpLl_1tcK0eeehzN980zbG-3M2nhbVks"
    snapshot.permissions = "public"
    snapshot.status = "sealed"
    snapshot.save(update_fields=["url", "permissions", "status"])
    save_output(snapshot, "singlefile")
    save_response_image(snapshot)
    archive = Path(snapshot.output_dir) / "archivewebpage/archivewebpage.wacz"
    archive.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parent / "fixtures/responsive-images/google-drive.wacz", archive)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="archivewebpage",
        status="succeeded",
        output_str=archive.name,
        output_files={archive.name: {"size": archive.stat().st_size, "mimetype": "application/wacz"}},
        output_size=archive.stat().st_size,
    )
    image = Path(snapshot.output_dir) / "screenshot/screenshot.png"
    image.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "publicsite/assets/social-card.png", image)
    screenshot_result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="screenshot",
        status="succeeded",
        output_str=image.name,
        output_files={image.name: {"size": image.stat().st_size, "mimetype": "image/png"}},
        output_size=image.stat().st_size,
    )
    script = r"""
const puppeteer = require('puppeteer');
const assert = require('node:assert/strict');
const {waitForVisibleCardPreviews} = require(process.env.SCREENSHOT_SCRIPT);
(async () => {
  const browser = await puppeteer.launch({
    executablePath: process.env.CHROME_BINARY, headless: true,
    // Match browser_runtime's CHROME_SANDBOX=False and the existing isolated browser tests.
    args: [...JSON.parse(process.env.CHROME_ARGS), '--no-sandbox'],
  });
  try {
    const page = await browser.newPage();
    page.on('requestfailed', request => console.error(JSON.stringify({url: request.url(), failure: request.failure()})));
    page.on('response', response => { if (response.status() >= 400) console.error(JSON.stringify({url: response.url(), status: response.status()})); });
    await page.setViewport({width: 1600, height: 1000});
    await page.evaluateOnNewDocument(() => localStorage.setItem('archivebox-snapshot-header-visible', 'false'));
    let releaseCard;
    const replayPainted = new Promise(resolve => { releaseCard = resolve; });
    let releaseReplay;
    const replayRequest = new Promise(resolve => { releaseReplay = resolve; });
    await page.exposeFunction('observeReplayPainted', () => releaseCard());
    await page.evaluateOnNewDocument(() => window.addEventListener('message', event => {
      if ([document.getElementById('main-frame')?.contentWindow, document.getElementById('replay-preload')?.contentWindow].includes(event.source)
          && event.data?.type === 'archivebox-replay-painted') window.observeReplayPainted();
    }));
    // Hold only the real HTTP request; Chrome still fetches unchanged server bytes.
    await page.setRequestInterception(true);
    const pendingRequests = [];
    page.on('request', request => {
      const task = (async () => {
        if (process.env.SELECTION === 'automatic' && request.url().includes(`/_card/${process.env.SCREENSHOT_CARD_ID}`)) await replayPainted;
        if (new URL(request.url()).pathname.endsWith('.wacz')) await replayRequest;
        await request.continue();
      })();
      pendingRequests.push(task);
      task.catch(() => {}); // Retain failures for the final Promise.all below.
    });
    const started = Date.now();
    const navigation = page.goto(process.env.SNAPSHOT_URL, {waitUntil: 'domcontentloaded'});
    await page.waitForFunction(() => document.querySelector('#main-frame')?.src.includes('/singlefile/content.html'));
    const staticFrame = await (await page.$('#main-frame')).contentFrame();
    await staticFrame.waitForFunction(() => document.body?.innerText.includes('ArchiveBox consolelog preview fixture'));
    assert.equal(await page.$eval('.selected-card[data-plugin-name]', card => card.dataset.pluginName), 'singlefile');
    assert.equal(await page.$('#replay-screenshot-cover'), null);
    if (['unsupported', 'explicit'].includes(process.env.SELECTION)) {
      if (process.env.SELECTION === 'unsupported') {
        assert.equal(await page.evaluate(() => window.isSecureContext), false);
        assert.equal(await page.evaluate(() => 'serviceWorker' in navigator), false);
      }
      assert.equal(await page.$('#replay-preload'), null);
      releaseReplay();
    } else {
      await page.waitForSelector('#replay-preload');
      const sameViewport = await page.evaluate(() => {
        window.originalReplayCandidate = document.getElementById('replay-preload');
        const main = document.getElementById('main-frame').getBoundingClientRect();
        const preload = window.originalReplayCandidate.getBoundingClientRect();
        return {main: [main.width, main.height], preload: [preload.width, preload.height]};
      });
      assert.deepEqual(sameViewport.main, sameViewport.preload);
      assert(sameViewport.main.every(size => size > 0));
      if (process.env.SELECTION === 'manual') {
        // A user changing the URL fragment selects a real card and cancels preload.
        await page.evaluate(() => { location.hash = 'screenshot/screenshot.png'; });
        await page.waitForFunction(() => document.querySelector('#main-frame')?.src.includes('/screenshot/screenshot.png'));
        assert.equal(await page.$('#replay-preload'), null);
        releaseReplay();
        await page.waitForNetworkIdle();
        assert.equal(await page.$eval('.selected-card[data-plugin-name]', card => card.dataset.pluginName), 'screenshot');
        assert.equal(await page.$eval('#main-frame', frame => frame.dataset.replayPainted), undefined);
      } else {
        const captureReady = waitForVisibleCardPreviews(page);
        releaseReplay();
        await captureReady;
        await page.waitForFunction(() => document.querySelector('#main-frame')?.dataset.replayPainted === '1', {timeout: 10000});
        assert(await page.evaluate(() => document.getElementById('main-frame') === window.originalReplayCandidate));
        assert.equal(await page.$eval('.selected-card[data-plugin-name]', card => card.dataset.pluginName), 'archivewebpage');
      }
    }
    const response = await navigation;
    assert.equal(response.status(), 200);
    if (await page.$eval('.header-bottom', header => header.hidden)) await page.click('.header-toggle');
    await waitForVisibleCardPreviews(page);
    const card = await page.$('.output-stack-embedded_media iframe');
    assert(card);
    const frame = await card.contentFrame();
    assert(frame);
    assert.equal(await frame.evaluate(() => document.readyState), 'complete');
    const images = await frame.evaluate(() => [...document.images].map(image => ({
      complete: image.complete, width: image.naturalWidth,
    })));
    assert(images.length > 0);
    assert(images.every(image => image.complete && image.width > 0));
    await page.screenshot({path: process.env.SCREENSHOT_PATH});
    console.log(JSON.stringify({
      selection: process.env.SELECTION, elapsedMs: Date.now() - started,
      ttfbMs: await page.evaluate(() => {
        const navigation = performance.getEntriesByType('navigation')[0];
        return navigation.responseStart - navigation.requestStart;
      }),
    }));
    // A still-connected card with a real server error must not be accepted.
    const missing = await frame.goto(new URL('/missing-gallery-card', frame.url()).href);
    assert.equal(missing.status(), 404);
    assert(await card.evaluate(iframe => iframe.isConnected));
    await assert.rejects(waitForVisibleCardPreviews(page, 500), /Waiting failed: 500ms exceeded/);
    await Promise.all(pendingRequests);
    if (process.env.SELECTION === 'automatic') {
      await page.setViewport({width: 390, height: 844});
      if (!(await page.$eval('.header-bottom', header => header.hidden))) await page.click('.header-toggle');
      await page.screenshot({path: process.env.SCREENSHOT_PATH.replace('.png', '-mobile.png')});
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [str(browser_runtime["node_binary"]), "-e", script],
        env={
            **os.environ,
            "NODE_PATH": str(browser_runtime["node_path"]),
            "CHROME_BINARY": str(browser_runtime["chrome_binary"]),
            "CHROME_ARGS": json.dumps(
                [
                    *browser_runtime["chrome_args"],
                    f"--host-resolver-rules=MAP *.{hostname} 127.0.0.1,MAP {hostname} 127.0.0.1",
                    "--no-proxy-server",
                ],
            ),
            "SELECTION": selection,
            "SCREENSHOT_CARD_ID": str(screenshot_result.id),
            "SCREENSHOT_SCRIPT": str(REPO_ROOT / "bin/take_screenshot.js"),
            "SNAPSHOT_URL": f"http://web.{hostname}:{port}{snapshot.get_absolute_url()}/index.html"
            + ("#singlefile/content.html" if selection == "explicit" else ""),
            "SCREENSHOT_PATH": str(tmp_path / "cards.png"),
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "cards.png").stat().st_size > 1000
    (tmp_path / "timings.json").write_text(json.dumps(json.loads(result.stdout), indent=2))


@pytest.mark.django_db(transaction=True)
def test_gallery_failure_retains_native_request_state_without_query_data(live_server, browser_runtime, tmp_path):
    failure_dir = tmp_path / "diagnostics"
    output = tmp_path / "failed.png"
    result = subprocess.run(
        [
            str(browser_runtime["node_binary"]),
            str(REPO_ROOT / "bin/take_screenshot.js"),
            f"{live_server.url}/?gallery_secret=never-retain#private-fragment",
            str(output),
        ],
        env={
            **os.environ,
            "NODE_PATH": str(browser_runtime["node_path"]),
            "CHROME_BINARY": str(browser_runtime["chrome_binary"]),
            "SCREENSHOT_FAILURE_DIR": str(failure_dir),
            # An incomplete CLI login configuration fails after the real HTTP navigation.
            "SCREENSHOT_LOGIN_USERNAME": "missing-password",
            "SCREENSHOT_LOGIN_PASSWORD": "",
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "SCREENSHOT_LOGIN_USERNAME and SCREENSHOT_LOGIN_PASSWORD must be set together" in result.stderr
    assert not output.exists()
    saved = (failure_dir / "failed.png.json").read_text()
    assert "gallery_secret" not in saved
    assert "never-retain" not in saved
    assert "private-fragment" not in saved
    evidence = json.loads(saved)
    assert evidence["frames"]
    assert evidence["documents"]
    assert any(record.get("status") == 200 and record["ttfbMs"] >= 0 for record in evidence["documents"])
