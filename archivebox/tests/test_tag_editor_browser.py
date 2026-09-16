"""Exercise shared tag controls against the real server and API in Chromium."""

import json
import os
import subprocess

import pytest

from archivebox.core.models import Tag
from archivebox.tests.conftest import cli_env, create_admin_and_token, get_free_port, start_archivebox_server, stop_server
from archivebox.tests.test_orm_helpers import use_archivebox_db
from archivebox.tests.test_server_security_browser import browser_runtime as browser_runtime


@pytest.mark.django_db(transaction=True)
def test_tag_editor_creates_autocompletes_and_synchronizes(initialized_archive, browser_runtime, tmp_path):
    create_admin_and_token(initialized_archive)
    port = get_free_port()
    env = cli_env(port=port, server=True)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    script = tmp_path / "tags.cjs"
    script.write_text(r"""
const assert = require('node:assert/strict');
const puppeteer = require('puppeteer');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
    const browser = await puppeteer.launch({executablePath: process.argv[2], headless: true, args: ['--no-sandbox']});
    try {
        const session = await browser.target().createCDPSession();
        await session.send('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: process.argv[4], eventsEnabled: true});
        const downloaded = new Promise(resolve => session.on('Browser.downloadProgress', event => {
            if (event.state === 'completed') resolve();
        }));
        const page = await browser.newPage();
        async function replaceText(selector, value) {
            await page.click(selector);
            await page.locator(selector).fill(value);
            assert.equal(await page.$eval(selector, node => node.value), value);
        }
        const errors = [];
        page.on('pageerror', error => errors.push(String(error)));
        const base = process.argv[3];
        await page.goto(base + '/admin/login/', {waitUntil: 'networkidle2'});
        await page.type('input[name="username"]', 'apitestadmin');
        await page.type('input[name="password"]', 'testpass123');
        await Promise.all([
            page.waitForNavigation({waitUntil: 'networkidle2'}),
            page.click('input[type="submit"], button[type="submit"]'),
        ]);
        await page.goto(base + '/add/', {waitUntil: 'networkidle2'});
        const input = '.tag-editor-container .tag-inline-input';
        const hidden = '.tag-editor-container input[type="hidden"]';
        await page.type(input, 'browser-alpha browser-beta');
        const created = page.waitForResponse(response => response.url().includes('/tags/create/') && response.request().postData().includes('browser-beta'));
        await page.keyboard.press('Enter');
        assert.equal((await created).status(), 200);
        assert.equal(await page.$eval(hidden, node => node.value), 'browser-alpha,browser-beta');
        assert.ok(page.url().endsWith('/add/'), 'Enter must not submit the add form');
        await page.type(input, 'BROWSER-ALPHA');
        await page.keyboard.press('Enter');
        assert.equal(await page.$$eval('.tag-editor-container .tag-pill', nodes => nodes.length), 2);
        await page.keyboard.press('Backspace');
        assert.equal(await page.$eval(hidden, node => node.value), 'browser-alpha');
        await page.click('.tag-editor-container .tag-remove-btn');
        assert.equal(await page.$eval(hidden, node => node.value), '');
        await page.type(input, 'browser-be');
        await page.waitForFunction(() => [...document.querySelectorAll('.tag-editor-container datalist option')].some(option => option.value === 'browser-beta'));
        await page.$eval(hidden, node => {
            node.value = 'gamma,delta,gamma';
            node.dispatchEvent(new Event('archivebox:sync-tags'));
        });
        assert.deepEqual(await page.$$eval('.tag-editor-container .tag-pill', nodes => nodes.map(node => node.dataset.tag)), ['delta', 'gamma']);
        await page.goto(base + '/admin/core/tag/', {waitUntil: 'networkidle2'});
        await page.type('#tag-live-search', 'browser-beta');
        await page.waitForFunction(() => document.querySelectorAll('.tag-card').length === 1 && document.querySelector('.tag-card').textContent.includes('browser-beta'));
        await page.click('[data-action="edit"]');
        await page.waitForSelector('.tag-card.is-editing');
        await page.click('[data-action="cancel-edit"]');
        assert.equal(await page.$('.tag-card.is-editing'), null);
        await page.click('[data-action="edit"]');
        await replaceText('.tag-card__rename input', 'browser-renamed');
        const renamed = page.waitForResponse(response => response.url().includes('/rename'));
        await page.click('[data-action="save-edit"]');
        const renameResponse = await renamed;
        assert.equal(renameResponse.status(), 200);
        assert.equal((await renameResponse.json()).tag_name, 'browser-renamed');
        await page.waitForFunction(() => document.querySelectorAll('.tag-card').length === 0);
        await replaceText('#tag-live-search', 'browser-renamed');
        await page.waitForFunction(() => document.querySelector('.tag-card__display strong')?.textContent === 'browser-renamed');
        const exported = page.waitForResponse(response => response.url().includes('/snapshots.jsonl'));
        await page.click('[data-action="download-jsonl"]');
        assert.equal((await exported).status(), 200);
        await downloaded;
        assert.equal(fs.readFileSync(path.join(process.argv[4], 'tag-browser-renamed-snapshots.jsonl'), 'utf8'), '');
        await page.type('#tag-create-name', 'browser-created');
        await page.click('#tag-create-form button[type="submit"]');
        await page.waitForFunction(() => document.querySelector('.tag-card__display strong')?.textContent === 'browser-created');
        page.once('dialog', dialog => dialog.accept());
        const deleted = page.waitForResponse(response => response.request().method() === 'DELETE');
        await page.click('[data-action="delete"]');
        const deleteResponse = await deleted.catch(async error => {
            throw new Error(error.message + ': ' + await page.$eval('#tag-toast', node => node.textContent));
        });
        assert.equal(deleteResponse.status(), 200);
        await page.waitForFunction(() => document.querySelectorAll('.tag-card').length === 0);
        assert.deepEqual(errors, []);
        console.log(JSON.stringify({errors}));
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
""")
    try:
        start_archivebox_server(initialized_archive, port=port, env=env)
        result = subprocess.run(
            [
                str(browser_runtime["node_binary"]),
                str(script),
                str(browser_runtime["chrome_binary"]),
                f"http://admin.archivebox.localhost:{port}",
                str(downloads),
            ],
            env={**os.environ, "NODE_PATH": str(browser_runtime["node_path"])},
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"errors": []}
        with use_archivebox_db(initialized_archive):
            assert set(Tag.objects.filter(name__startswith="browser-").values_list("name", flat=True)) == {
                "browser-alpha",
                "browser-renamed",
            }
    finally:
        stop_server(initialized_archive)
