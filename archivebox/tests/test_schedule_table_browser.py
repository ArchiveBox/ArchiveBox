"""The schedule's shared snapshot table uses real browser forms and model actions."""

import os
import json
import hashlib
from pathlib import Path
import subprocess

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.tests.conftest import cli_env, create_admin_and_token, get_free_port, start_archivebox_server, stop_server
from archivebox.tests.test_orm_helpers import use_archivebox_db
from archivebox.tests.test_server_security_browser import browser_runtime as browser_runtime
from archivebox.workers.models import RETRY_AT_MAX


@pytest.mark.django_db(transaction=True)
def test_schedule_snapshot_search_status_and_actions(initialized_archive, browser_runtime, tmp_path):
    create_admin_and_token(initialized_archive)
    with use_archivebox_db(initialized_archive):
        user = get_user_model().objects.get(username="apitestadmin")
        crawl = Crawl.objects.create(
            urls="https://example.com/schedule",
            created_by=user,
            status=Crawl.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
        )
        schedule = CrawlSchedule.objects.create(template=crawl, schedule="0 0 1 1 *", created_by=user)
        paused = Snapshot.objects.create(crawl=crawl, url="https://example.com/matching", status="paused", retry_at=RETRY_AT_MAX)
        Snapshot.objects.create(crawl=crawl, url="https://example.com/sealed", status="sealed", retry_at=None)
        change_path = reverse("admin:crawls_crawlschedule_change", args=[schedule.pk])
        paused_id = str(paused.pk)
    port = get_free_port()
    script = tmp_path / "schedule.cjs"
    script.write_text(r"""
const assert = require('node:assert/strict');
const puppeteer = require('puppeteer');
(async () => {
    const browser = await puppeteer.launch({executablePath: process.argv[2], headless: true, args: ['--no-sandbox']});
    try {
        const page = await browser.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(String(error)));
        const base = process.argv[3], path = process.argv[4];
        let submission = {};
        page.on('request', request => {
            if (request.method() === 'POST' && new URL(request.url()).pathname === '/admin/core/snapshot/') {
                const fields = new URLSearchParams(request.postData());
                submission = Object.fromEntries(['action', 'tags', '_selected_action', 'index', 'select_across'].map(key => [key, fields.getAll(key)]));
            }
        });
        await page.goto(base + '/admin/login/', {waitUntil: 'networkidle2'});
        await page.type('input[name="username"]', 'apitestadmin');
        await page.type('input[name="password"]', 'testpass123');
        await Promise.all([page.waitForNavigation({waitUntil: 'networkidle2'}), page.click('input[type="submit"], button[type="submit"]')]);
        await page.goto(base + path, {waitUntil: 'networkidle2'});
        await page.waitForFunction(() => document.querySelector('#crawl-tree')?.textContent.includes('Crawl is paused.'));
        assert.ok(await page.$eval('#progress-monitor', monitor => getComputedStyle(monitor).backgroundImage.includes('linear-gradient')));
        assert.equal(await page.$eval('#progress-monitor', monitor => monitor.classList.contains('collapsed')), true);
        await page.click('#progress-collapse');
        assert.equal(await page.$eval('#progress-monitor', monitor => monitor.classList.contains('collapsed')), false);
        assert.equal(await page.$eval('#progress-collapse', button => button.getAttribute('aria-expanded')), 'true');
        assert.equal(await page.$$eval('input.action-select', rows => rows.length), 2);
        assert.equal(await page.$eval('input.action-select', input => input.form.id), 'changelist-form');
        assert.equal(await page.$eval('#id_schedule', input => input.form.id), 'crawlschedule_form');
        await Promise.all([
            page.waitForNavigation({waitUntil: 'networkidle2'}),
            page.select('#changelist-search select[name="snapshot_status"]', 'paused'),
        ]);
        assert.equal(await page.$$eval('input.action-select', rows => rows.length), 1);
        assert.equal(new URL(page.url()).searchParams.get('snapshot_status'), 'paused');
        await page.type('#searchbar', 'matching');
        await Promise.all([page.waitForNavigation({waitUntil: 'networkidle2'}), page.keyboard.press('Enter')]);
        assert.equal(await page.$$eval('input.action-select', rows => rows.length), 1);
        assert.equal(await page.$$eval('input.action-select:checked', rows => rows.length), 1, 'The table auto-selects its sole visible row');
        await page.click('input.action-select');
        assert.equal(await page.$$eval('input.action-select:checked', rows => rows.length), 0);
        await page.click('input.action-select');
        assert.equal(await page.$$eval('input.action-select:checked', rows => rows.length), 1, 'Selecting the row must check its action input');
        await page.type('#changelist-form .tag-inline-input', 'schedule-browser-tag');
        await page.keyboard.press('Enter');
        await page.waitForFunction(() => document.querySelector('#changelist-form input[name="tags"]').value === 'schedule-browser-tag');
        assert.equal(await page.$eval('#changelist-form', form => new FormData(form).getAll('_selected_action').length), 1, 'The selected row must belong to the action form');
        await Promise.all([
            page.waitForNavigation({waitUntil: 'networkidle2'}),
            page.click('#changelist-form .actions-top .button[name="add_tags"]'),
        ]);
        assert.ok(new URL(page.url()).pathname.endsWith('/admin/core/snapshot/'));
        for (const [mode, pathSuffix] of [['grid', '/admin/core/snapshot/grid/'], ['list', '/admin/core/snapshot/']]) {
            await Promise.all([page.waitForNavigation({waitUntil: 'networkidle2'}), page.click('#snapshot-view-toggle')]);
            assert.equal(new URL(page.url()).pathname, pathSuffix);
            assert.equal(await page.evaluate(() => localStorage.getItem('preferred_snapshot_view_mode')), mode);
        }
        await page.evaluate(() => localStorage.setItem('admin-filters-collapsed', 'false'));
        await page.goto(base + '/admin/core/archiveresult/', {waitUntil: 'networkidle2'});
        assert.equal(await page.$eval('#changelist-filter-toggle', button => button.getAttribute('aria-expanded')), 'true');
        await page.click('#changelist-filter-toggle');
        assert.equal(await page.$eval('#changelist-filter-toggle', button => button.getAttribute('aria-expanded')), 'false');
        await page.click('#changelist-toolbar-filter-toggle');
        assert.equal(await page.$eval('#changelist-filter-toggle', button => button.getAttribute('aria-expanded')), 'true');
        for (const [profile, width, height] of [['desktop', 1600, 1000], ['tablet', 1024, 1366], ['mobile', 390, 844]]) {
            await page.setViewport({width, height});
            await page.screenshot({path: process.argv[5] + '/' + profile + '.png'});
        }
        assert.deepEqual(errors, []);
        console.log(JSON.stringify({submission, messages: await page.$$eval('.messagelist', nodes => nodes.map(node => node.textContent))}));
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
""")
    try:
        start_archivebox_server(initialized_archive, port=port, env=cli_env(port=port, server=True))
        result = subprocess.run(
            [
                str(browser_runtime["node_binary"]),
                str(script),
                str(browser_runtime["chrome_binary"]),
                f"http://admin.archivebox.localhost:{port}",
                change_path,
                str(tmp_path),
            ],
            env={**os.environ, "NODE_PATH": str(browser_runtime["node_path"])},
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        manifest = tmp_path / "manifest.jsonl"
        manifest.write_text(
            "\n".join(
                json.dumps(
                    {
                        "name": "Archive results",
                        "profile": profile,
                        "filename": f"{profile}.png",
                        "url": f"http://admin.archivebox.localhost:{port}/admin/core/archiveresult/",
                        "source": "archivebox/core/admin_archiveresults.py",
                    },
                )
                for profile in ("desktop", "tablet", "mobile")
            ),
        )
        repo_root = Path(__file__).resolve().parents[2]
        gallery = tmp_path / "index.html"
        built = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(repo_root),
                "--no-sync",
                "python",
                str(repo_root / "bin/generate_ui_screenshot_gallery.py"),
                "build",
                str(manifest),
                str(gallery),
            ],
            cwd=initialized_archive,
            env={**os.environ, "UI_SCREENSHOT_ALLOW_PARTIAL": "1"},
            capture_output=True,
            text=True,
        )
        assert built.returncode == 0, built.stderr
        provenance = json.loads((tmp_path / "build.json").read_text())
        assert provenance["capture_count"] == 3
        for profile in ("desktop", "tablet", "mobile"):
            filename = f"{profile}.png"
            digest = hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest()
            assert provenance["files"][filename] == digest
            assert f"{filename}?v={digest[:12]}" in gallery.read_text()
        with use_archivebox_db(initialized_archive):
            assert list(Snapshot.objects.get(pk=paused_id).tags.values_list("name", flat=True)) == ["schedule-browser-tag"], result.stdout
            assert not Snapshot.objects.exclude(pk=paused_id).filter(tags__name="schedule-browser-tag").exists()
            assert CrawlSchedule.objects.get(pk=schedule.pk).schedule == "0 0 1 1 *"
    finally:
        stop_server(initialized_archive)
