"""Exercise the real agent wrapper with Chromium's native storage failures."""

import json
import os
import subprocess

import pytest

from .conftest import get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process
from .test_opencode_agent import _set_archivebox_config
from .test_opencode_agent import installed_opencode as installed_opencode
from .test_opencode_agent import opencode_archive_config as opencode_archive_config
from .test_server_security_browser import browser_runtime as browser_runtime


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def agent_server(installed_opencode, browser_runtime):
    port = get_free_port()
    url = f"http://localhost:{port}"
    config = installed_opencode.config
    _set_archivebox_config(
        config.data_dir,
        f"BASE_URL={url}",
        "SERVER_SECURITY_MODE=safe-onedomain-nojsreplay",
    )
    user = run_archivebox_cmd(
        [
            "shell",
            "-c",
            "from django.contrib.auth import get_user_model; get_user_model().objects.create_superuser(username='agent-browser-test', password='test-password')",
        ],
        cwd=config.data_dir,
        env=config.env,
    )
    assert user.returncode == 0, user.stderr or user.stdout
    process = start_archivebox_server(config.data_dir, port=port, env=config.env, log_name="agent-browser-server.log")
    try:
        yield url, config.data_dir
    finally:
        stop_archivebox_process(process)


def test_agent_preserves_projects_and_survives_storage_failure(agent_server, browser_runtime):
    server_url, data_dir = agent_server
    script = r"""
const assert = require('node:assert/strict');
const puppeteer = require('puppeteer');
const config = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
(async () => {
  for (const disabled of [false, true]) {
    const browser = await puppeteer.launch({
      executablePath: config.chrome,
      headless: true,
      // Headless interaction must not depend on the desktop display clock.
      args: ['--no-sandbox', '--disable-frame-rate-limit', ...(disabled ? ['--disable-local-storage'] : [])],
    });
    try {
      const page = await browser.newPage();
      await page.goto(new URL('/admin/login/', config.url).href, {waitUntil: 'domcontentloaded'});
      await page.locator('#login-form input[name="username"]').fill('agent-browser-test');
      await page.locator('#login-form input[name="password"]').fill('test-password');
      assert.equal(await page.$eval('#login-form input[name="username"]', element => element.value), 'agent-browser-test');
      assert.equal(await page.$eval('#login-form input[name="password"]', element => element.value), 'test-password');
      await Promise.all([
        page.waitForNavigation({waitUntil: 'domcontentloaded'}),
        page.locator('#login-form input[type="submit"]').click(),
      ]);
      assert.ok(!page.url().includes('/admin/login/'), page.url());
      assert.equal((await page.goto(config.url, {waitUntil: 'domcontentloaded'})).status(), 200);
      const welcome = '#opencode-agent-welcome';
      await page.waitForSelector(welcome, {visible: true});
      if (disabled) {
        assert.equal(await page.evaluate(() => {
          try { return localStorage === null; }
          catch (error) { if (error.name !== 'SecurityError') throw error; return true; }
        }), true);
      } else {
        await page.click('#opencode-agent-welcome-dismiss');
        await page.waitForSelector(welcome, {hidden: true});
        await page.reload({waitUntil: 'domcontentloaded'});
        assert.equal(await page.$eval(welcome, element => element.hidden), true);
        const existing = {
          list: [{type: 'http', http: {url: 'http://other.example'}}],
          projects: {
            local: [{worktree: '/other-project', expanded: false}],
            'http://other.example': [{worktree: '/remote-project', expanded: true}],
          },
          lastProject: {'http://other.example': '/remote-project'},
        };
        await page.evaluate(value => localStorage.setItem('opencode.global.dat:server', JSON.stringify(value)), existing);
        await page.reload({waitUntil: 'domcontentloaded'});
        await page.waitForFunction(workdir => {
          const state = JSON.parse(localStorage.getItem('opencode.global.dat:server'));
          return state.projects.local?.some(project => project.worktree === workdir);
        }, {}, config.workdir);
        const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('opencode.global.dat:server')));
        assert.deepEqual(saved.list, existing.list);
        assert.deepEqual(saved.projects['http://other.example'], existing.projects['http://other.example']);
        assert.equal(saved.lastProject['http://other.example'], '/remote-project');
        const projects = saved.projects.local;
        assert.ok(Array.isArray(projects), JSON.stringify({url: page.url(), saved, existing}));
        assert.deepEqual(projects.find(project => project.worktree === '/other-project'), {worktree: '/other-project', expanded: false});
        assert.equal(projects.filter(project => project.worktree === config.workdir).length, 1);
        await page.reload({waitUntil: 'domcontentloaded'});
        assert.equal(await page.evaluate(workdir => {
          const state = JSON.parse(localStorage.getItem('opencode.global.dat:server'));
          return state.projects.local.filter(project => project.worktree === workdir).length;
        }, config.workdir), 1);

        // Fill the actual browser quota; do not replace or intercept Storage methods.
        const failure = await page.evaluate(() => {
          localStorage.clear();
          let low = 0, high = 8 * 1024 * 1024;
          while (low < high) {
            const size = Math.ceil((low + high) / 2);
            try { localStorage.setItem('padding', 'x'.repeat(size)); low = size; }
            catch (error) { if (error.name !== 'QuotaExceededError') throw error; high = size - 1; }
          }
          try { localStorage.setItem('extra', '1'); return null; }
          catch (error) { return error.name; }
        });
        assert.equal(failure, 'QuotaExceededError');
        await page.reload({waitUntil: 'domcontentloaded'});
        await page.waitForSelector(welcome, {visible: true});
      }
      await page.click('#opencode-agent-welcome-dismiss');
      await page.waitForSelector(welcome, {hidden: true});
      assert.equal((await page.goto(new URL('/add/', config.url).href, {waitUntil: 'domcontentloaded'})).status(), 200);
    } finally {
      await browser.close();
    }
  }
  console.log('AGENT_STORAGE_FAILURE_ISOLATED');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [str(browser_runtime["node_binary"]), "-e", script],
        input=json.dumps(
            {
                "chrome": str(browser_runtime["chrome_binary"]),
                "url": f"{server_url}/admin/agent",
                "workdir": str(data_dir.resolve()),
            },
        ),
        env={**os.environ, "NODE_PATH": browser_runtime["node_path"]},
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "AGENT_STORAGE_FAILURE_ISOLATED" in result.stdout
