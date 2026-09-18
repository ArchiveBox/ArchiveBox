"""Exercise the rendered Django config widget in real Chromium."""

import json
import os
import subprocess

from archivebox.base_models.admin import KeyValueWidget
from archivebox.tests.test_server_security_browser import browser_runtime as browser_runtime


def test_config_editor_rows_validation_and_serialization(browser_runtime, tmp_path):
    html = str(KeyValueWidget().render("config", {"API_KEY": "private-test-value", "CHROME_WAIT_FOR": "load"}, attrs={"id": "id_config"}))
    assert "private-test-value" not in html
    page_path = tmp_path / "config.html"
    page_path.write_text(f"<!doctype html><form>{html}</form>")
    script_path = tmp_path / "config.cjs"
    script_path.write_text(r"""
const assert = require('node:assert/strict');
const puppeteer = require('puppeteer');
(async () => {
    const browser = await puppeteer.launch({executablePath: process.argv[2], headless: true, args: ['--no-sandbox']});
    try {
        const page = await browser.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(String(error)));
        await page.goto(process.argv[3], {waitUntil: 'load'});
        const secret = await page.$eval('input[data-sensitive]', input => ({type: input.type, value: input.value}));
        assert.deepEqual(secret, {type: 'password', value: ''});
        const rowSelector = '#id_config_rows .key-value-row';
        const before = await page.$$eval(rowSelector, rows => rows.length);
        const cases = [
            ['TIMEOUT', '42', 42, ''],
            ['CHECK_SSL_VALIDITY', 'False', false, ''],
            ['CHROME_WAIT_FOR', 'load', 'load', ''],
            ['CHROME_RESOLUTION', 'abc', 'abc', 'Must match pattern'],
            ['CUSTOM_BINARY', '/usr/bin/wget', '/usr/bin/wget', ''],
            ['CUSTOM_BINARY', '"wget"', '"wget"', 'Binary paths cannot contain quotes'],
            ['URL_ALLOWLIST', '[', '[', 'Invalid regex'],
        ];
        for (const [key, value, stored, error] of cases) {
            await page.click('button[onclick="addKeyValueRow_id_config()"]');
            await page.type(rowSelector + ':last-child .kv-key', key);
            await page.type(rowSelector + ':last-child .kv-value', value);
            const result = await page.$eval('#id_config', input => JSON.parse(input.value));
            assert.deepEqual(result[key], stored);
            const message = await page.$eval(rowSelector + ':last-child .kv-value', input => input.title);
            if (error) assert.ok(message.includes(error), `${key}: ${message}`);
            else assert.equal(message, '');
            await page.click(rowSelector + ':last-child button');
            assert.equal(await page.$$eval(rowSelector, rows => rows.length), before);
        }
        const options = await page.$$eval('.kv-value-options option', options => options.map(option => option.value));
        assert.ok(options.includes('networkidle0'));
        assert.deepEqual(errors, []);
        console.log(JSON.stringify({cases: cases.length, errors}));
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
""")
    result = subprocess.run(
        [str(browser_runtime["node_binary"]), str(script_path), str(browser_runtime["chrome_binary"]), page_path.as_uri()],
        env={**os.environ, "NODE_PATH": str(browser_runtime["node_path"])},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"cases": 7, "errors": []}
