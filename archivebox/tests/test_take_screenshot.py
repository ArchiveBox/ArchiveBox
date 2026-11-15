"""Gallery capture waits for real lazy card documents and decoded pixels."""

import json
import os
import subprocess
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from abx_plugins import get_plugins_dir

from archivebox.core.models import ArchiveResult
from archivebox.machine.models import Machine
from archivebox.tests.conftest import REPO_ROOT, resolve_abxpkg_binary_env
from archivebox.tests.test_snapshot_output_stacks import save_output, save_response_image


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("selection", ["automatic", "manual", "unsupported", "explicit"])
def test_gallery_keeps_static_preview_until_real_replay_is_ready(snapshot, live_server, browser_runtime, tmp_path, selection):
    # Copying a WACZ does not install its viewer. A cold browser-only runtime
    # must not depend on another test having captured with ArchiveWeb.page.
    resolve_abxpkg_binary_env(
        browser_runtime["lib_dir"],
        deps_from=Path(get_plugins_dir()) / "archivewebpage" / "config.json",
    )
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
    const savedDocument = await (await staticFrame.waitForSelector('#document')).contentFrame();
    await savedDocument.waitForFunction(() => document.body?.innerText.includes('ArchiveBox consolelog preview fixture'));
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
    if (process.env.SELECTION === 'automatic') {
      const replay = page.frames().find(frame => frame.url().includes('/replay/w/'));
      assert(replay);
      assert(await replay.evaluate(() => document.body.innerText.includes('Drive')));
      for (const [width, height] of [[1600, 1000], [390, 844], [640, 240]]) {
        await page.setViewport({width, height});
        for (const expanded of [true, false]) {
          await page.evaluate(() => scrollTo(0, 0));
          if (await page.$eval('.header-bottom', header => !header.hidden) !== expanded) await page.click('.header-toggle');
          await replay.waitForFunction(() => document.documentElement.scrollHeight <= innerHeight + 1);
          assert.equal(await replay.evaluate(() => scrollY), 0);
          if (process.env.REPLAY_VISUAL_DIR) {
            await page.screenshot({path: `${process.env.REPLAY_VISUAL_DIR}/wacz-${width}x${height}-${expanded}.png`});
          }
          const position = await page.$eval('#main-frame', frame => frame.getBoundingClientRect().top + scrollY);
          await page.evaluate(y => scrollTo(0, y), position);
          const previous = await page.evaluate(() => scrollY);
          await page.mouse.move(width / 2, height / 2);
          await page.mouse.wheel({deltaY: 600});
          await page.waitForFunction(previous => scrollY > previous, {}, previous);
          assert.equal(await replay.evaluate(() => scrollY), 0);
          if (process.env.REPLAY_VISUAL_DIR) {
            await page.screenshot({path: `${process.env.REPLAY_VISUAL_DIR}/wacz-${width}x${height}-${expanded}-scrolled.png`});
          }
        }
      }
      await page.setViewport({width: 1600, height: 1000});
      await page.evaluate(() => scrollTo(0, 0));
      if (await page.$eval('.header-bottom', header => header.hidden)) await page.click('.header-toggle');
    }
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("view", ["folder", "unfiltered", "smart", "search", "folder-menu", "import-menu"])
def test_gallery_navigation_validates_real_folder_filter_report(snapshot, admin_user, live_server, browser_runtime, tmp_path, view):
    from archivebox.core.models import Folder

    folder = Folder.objects.create(name="📥 Gallery inbox" if view == "search" else "Gallery navigation", created_by=admin_user)
    if view == "search":
        Folder.objects.create(name="Other folder", position=1, created_by=admin_user)
    snapshot.folder = folder
    snapshot.save(update_fields=["folder"])
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    path = "/admin/core/snapshot/"
    expected = f"{path}?folder={folder.pk}&q="
    target = expected if view != "unfiltered" else path
    admin_url = f"http://admin.archivebox.localhost:{port}"
    if view == "smart":
        snapshot.url = "https://news.ycombinator.com/"
        snapshot.status = "sealed"
        snapshot.save(update_fields=["url", "status"])
        save_output(snapshot, "singlefile")
        assert save_response_image(snapshot).output_size > 1024
        prepared = subprocess.run(
            [
                str(browser_runtime["node_binary"]),
                "-e",
                r"""
const puppeteer = require('puppeteer');
const {prepareSmartFolder} = require(process.env.LIBRARY_GALLERY);
(async () => {
  const browser = await puppeteer.launch({executablePath: process.env.CHROME_BINARY, headless: true, args: [...JSON.parse(process.env.CHROME_ARGS), '--no-sandbox']});
  try {
    const page = await browser.newPage();
    await page.setViewport({width: 1600, height: 1000});
    await page.goto(`${process.env.ADMIN_URL}/admin/login/`, {waitUntil: 'domcontentloaded'});
    await page.type('#id_username', process.env.LOGIN_USERNAME);
    await page.type('#id_password', 'testpassword');
    await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}), page.click('button[type="submit"], input[type="submit"]')]);
    const result = await prepareSmartFolder(page, process.env.ADMIN_URL, process.env.CRAWL_ID);
    console.log(JSON.stringify(result));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
""",
            ],
            env={
                **os.environ,
                "NODE_PATH": str(browser_runtime["node_path"]),
                "CHROME_BINARY": str(browser_runtime["chrome_binary"]),
                "CHROME_ARGS": json.dumps(browser_runtime["chrome_args"]),
                "LIBRARY_GALLERY": str(REPO_ROOT / "archivebox/core/library_gallery.js"),
                "ADMIN_URL": admin_url,
                "LOGIN_USERNAME": admin_user.username,
                "CRAWL_ID": str(snapshot.crawl_id),
            },
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        gallery = json.loads(prepared.stdout)
        expected = gallery["path"]
        actual_url = urlsplit(gallery["url"])
        target = actual_url.path + "?" + actual_url.query
    output = tmp_path / "folder.png"
    capture = subprocess.run(
        [
            str(browser_runtime["node_binary"]),
            str(REPO_ROOT / "bin/take_screenshot.js"),
            admin_url + target,
            str(output),
        ],
        env={
            **os.environ,
            "NODE_PATH": str(browser_runtime["node_path"]),
            "CHROME_BINARY": str(browser_runtime["chrome_binary"]),
            "SCREENSHOT_LOGIN_USERNAME": admin_user.username,
            "SCREENSHOT_LOGIN_PASSWORD": "testpassword",
            "SCREENSHOT_WAIT_SELECTOR": "#result_list input.action-select",
            **(
                {
                    "SCREENSHOT_LIBRARY_MENU": {"search": "search", "folder-menu": "folder", "import-menu": "import"}[view],
                    "SCREENSHOT_VARIANTS_JSON": json.dumps(
                        [
                            {"path": str(output), "width": 1600, "height": 1000},
                            {"path": str(tmp_path / "folder-tablet.png"), "width": 1024, "height": 1366},
                            {"path": str(tmp_path / "folder-mobile.png"), "width": 390, "height": 844},
                        ],
                    ),
                }
                if view in {"search", "folder-menu", "import-menu"}
                else {}
            ),
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert capture.returncode == 0, capture.stdout + capture.stderr
    assert output.stat().st_size > 1000
    report = tmp_path / "folder.json"
    report.write_text(capture.stdout)
    assert json.loads(report.read_text())["checks"]["status"] == 200

    def validate(expected_path):
        return subprocess.run(
            [
                "uv",
                "run",
                "--no-sync",
                "--project",
                str(REPO_ROOT),
                "python",
                str(REPO_ROOT / "bin/generate_ui_screenshot_gallery.py"),
                "validate",
                str(report),
                expected_path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

    assert validate(path).returncode == 0  # Existing path-only callers allow query strings.
    matching = validate(expected)
    assert matching.returncode == (1 if view == "unfiltered" else 0), matching.stdout + matching.stderr
    if view == "folder":
        reordered = validate(f"{path}?q=&folder={folder.pk}")
        assert reordered.returncode == 0, reordered.stderr
    elif view == "unfiltered":
        assert "expected final query" in matching.stderr
    wrong_folder = validate(f"{path}?folder=wrong-folder&q=")
    assert wrong_folder.returncode == 1
    assert "expected final query" in wrong_folder.stderr
    wrong_path = validate("/admin/core/tag/")
    assert wrong_path.returncode == 1
    assert "expected final path" in wrong_path.stderr
