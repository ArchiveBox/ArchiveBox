"""Capture two real pages, remove their source, then exercise native replay/export."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from archivebox.crawls.models import Crawl
from archivebox.tests.test_orm_helpers import use_archivebox_db

from .conftest import cli_env, get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process


REPO = Path(__file__).resolve().parents[2]


@pytest.mark.django_db(transaction=True)
def test_gallery_native_site_navigation(initialized_archive, browser_runtime):
    root = initialized_archive
    exports = root / "site-exports"
    source = exports / "site-navigation"
    shutil.copytree(REPO / "archivebox/tests/fixtures/site-navigation", source)
    port, static_port = get_free_port(), get_free_port()
    env = cli_env(
        BASE_URL=f"http://archivebox.localhost:{port}",
        BIND_ADDR=f"127.0.0.1:{port}",
        DJANGO_SUPERUSER_USERNAME="replay-review",
        DJANGO_SUPERUSER_PASSWORD="local-replay-test-password",
        DJANGO_SUPERUSER_EMAIL="replay@example.com",
        ABXPKG_LIB_DIR=str(browser_runtime["lib_dir"]),
        NODE_PATH=browser_runtime["node_path"],
        NODE_BINARY=str(browser_runtime["node_binary"]),
        CHROME_BINARY=str(browser_runtime["chrome_binary"]),
        CHROME_HEADLESS="True",
        CHROME_SANDBOX="False",
        CHROME_ISOLATION="snapshot",
        PLUGINS="chrome,wget,archivewebpage,title,parse_dom_outlinks",
        SEARCH_BACKEND_ENGINE="sqlite",
    )
    created = run_archivebox_cmd(["manage", "createsuperuser", "--noinput"], cwd=root, env=env, timeout=60)
    assert created.returncode == 0, created.stdout + created.stderr
    static = subprocess.Popen(
        [
            "uv",
            "run",
            "--no-sync",
            "--project",
            str(REPO),
            "python",
            str(REPO / "bin/serve_ui_screenshot_exports.py"),
            str(static_port),
            "--directory",
            str(exports),
        ],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=(root / "static-server.log").open("w"),
        text=True,
    )
    server = None
    try:
        assert static.stdout.readline().startswith("Serving gallery exports on http://127.0.0.1:")
        script = root / "native-replay.cjs"
        script.write_text(r"""
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');
const [repo, base, staticBase, directory, phase] = process.argv.slice(2);
(async () => {
  const browser = await puppeteer.launch({executablePath: process.env.CHROME_BINARY, headless: true,
    args: ['--no-sandbox'], defaultViewport: {width: 1600, height: 1000}});
  try {
    const page = await browser.newPage();
    await page.goto(base + '/admin/login/');
    await page.type('#id_username', process.env.DJANGO_SUPERUSER_USERNAME);
    await page.type('#id_password', process.env.DJANGO_SUPERUSER_PASSWORD);
    await Promise.all([page.waitForNavigation(), page.click('input[type="submit"]')]);
    const gallery = require(path.join(repo, 'archivebox/domains/gallery.js'));
    const cloneFile = path.join(directory, '../clone.json');
    if (phase === 'capture') {
      const clone = await gallery.prepare(page, base, new URL('site-navigation/index.html', staticBase).href);
      fs.writeFileSync(cloneFile, JSON.stringify(clone));
    } else {
      const clone = JSON.parse(fs.readFileSync(cloneFile));
      const views = [
        ...await gallery.replayViews(page, clone),
        ...await gallery.exportViews(page, clone, directory, staticBase),
        ...await require(path.join(repo, 'archivebox/domains/wacz_gallery.js')).exportViews(page, clone, directory, staticBase),
      ];
      fs.writeFileSync(path.join(directory, '../replay-proof.json'), JSON.stringify(views, null, 2));
      await page.screenshot({path: path.join(directory, '../wacz-navigation.png')});
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
""")
        args = [
            str(browser_runtime["node_binary"]),
            str(script),
            str(REPO),
            f"http://admin.archivebox.localhost:{port}",
            f"http://127.0.0.1:{static_port}/",
            str(exports),
        ]
        server = start_archivebox_server(root, port=port, env=env, log_name="server.log")
        submitted = subprocess.run([*args, "capture"], cwd=root, env=env, capture_output=True, text=True, timeout=120)
        assert submitted.returncode == 0, submitted.stdout + submitted.stderr
        stop_archivebox_process(server)
        server = None
        clone = json.loads((root / "clone.json").read_text())
        captured = run_archivebox_cmd(["run", "--crawl-id", clone["crawlId"]], cwd=root, env=env, timeout=300)
        assert captured.returncode == 0, captured.stdout + captured.stderr
        with use_archivebox_db(root):
            crawl = Crawl.objects.get(pk=clone["crawlId"])
            assert crawl.urls.splitlines()[0] == clone["homeUrl"]
            assert crawl.config["CRAWL_MAX_URLS"] == 2
            assert crawl.config["ONLY_NEW"]
            assert crawl.url_passes_filters(clone["homeUrl"])
            assert crawl.url_passes_filters(clone["nextUrl"])
            for url in (clone["homeUrl"] + "?other=1", clone["nextUrl"] + "?other=1", clone["homeUrl"].replace("index.html", "third.html")):
                assert not crawl.url_passes_filters(url), url
            assert set(crawl.snapshot_set.values_list("url", flat=True)) == {clone["homeUrl"], clone["nextUrl"]}
        recordings = {file: hashlib.sha256(file.read_bytes()).hexdigest() for file in (root / "archive").rglob("archivewebpage.wacz")}
        assert len(recordings) == 2
        # Replays must use saved HTML/CSS/images and unmodified native WACZs.
        # The same static server still serves exports, but the source is gone.
        shutil.rmtree(source)
        server = start_archivebox_server(root, port=port, env=env, log_name="replay-server.log")
        proof = subprocess.run([*args, "replay"], cwd=root, env=env, capture_output=True, text=True, timeout=240)
        assert proof.returncode == 0, proof.stdout + proof.stderr
        views = json.loads((root / "replay-proof.json").read_text())
        assert len(views) == 8
        assert [view["path"] for view in views[:2]] == ["/site-navigation/index.html", "/site-navigation/chapter.html"]
        assert all(hashlib.sha256(file.read_bytes()).hexdigest() == digest for file, digest in recordings.items())
        assert {view["name"] for view in views} >= {
            "Captured internal link replay",
            "Static export internal navigation",
            "WACZ export internal navigation",
        }
    finally:
        if server is not None:
            stop_archivebox_process(server)
        static.terminate()
        static.wait(timeout=15)
