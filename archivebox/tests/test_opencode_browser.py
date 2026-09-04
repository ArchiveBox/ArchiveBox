"""Exercise the real agent wrapper with Chromium's native storage failures."""

import asyncio
import json
import os
import re
import subprocess

import pytest
import requests

from .conftest import get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process
from .test_opencode_agent import _set_archivebox_config
from .test_opencode_agent import installed_opencode as installed_opencode
from .test_opencode_agent import live_opencode as live_opencode
from .test_opencode_agent import opencode_archive_config as opencode_archive_config
from .test_server_security_browser import browser_runtime as browser_runtime


pytestmark = pytest.mark.django_db(transaction=True)


def test_agent_navigation_stays_inside_mount(agent_server, browser_runtime):
    server_url, _, _ = agent_server
    script = r"""
const assert = require('node:assert/strict');
const puppeteer = require('puppeteer');
const config = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
(async () => {
  const browser = await puppeteer.launch({executablePath: config.chrome, headless: true,
    args: ['--no-sandbox', '--disable-frame-rate-limit']});
  try {
    const page = await browser.newPage();
    await page.setViewport({width: 1440, height: 900});
    await page.goto(config.url + '/admin/login/', {waitUntil: 'domcontentloaded'});
    await page.locator('#login-form input[name="username"]').fill('agent-browser-test');
    await page.locator('#login-form input[name="password"]').fill('test-password');
    await Promise.all([page.waitForNavigation({waitUntil: 'domcontentloaded'}),
      page.locator('#login-form input[type="submit"]').click()]);
    assert.equal((await page.goto(config.url + '/admin/agent', {waitUntil: 'domcontentloaded'})).status(), 200);
    await page.locator('#opencode-agent-welcome-dismiss').click();
    const frame = await (await page.waitForSelector('iframe')).contentFrame();
    await frame.waitForSelector('a[href*="/session"]');
    const links = await frame.$$eval('a[href*="/session"]', nodes => nodes.map(node => node.getAttribute('href')));
    assert.ok(links.length, 'OpenCode must expose session navigation');
    for (const href of links) assert.ok(href.startsWith('/admin/agent/opencode/'), href);
    await frame.locator('::-p-aria(New session[role="button"])').click();
    await frame.waitForSelector('[contenteditable="true"]');
    let navigation;
    for (const link of await frame.$$('a[href*="/session"]')) {
      if (await link.isVisible() && await link.evaluate(node => node.href) !== frame.url()) {
        navigation = link;
        break;
      }
    }
    assert.ok(navigation, 'A visible link must navigate to another session route');
    await navigation.click();
    await frame.waitForSelector('[contenteditable="true"]');
    assert.ok(new URL(frame.url()).pathname.startsWith('/admin/agent/opencode/'), frame.url());
    const sessionUrl = frame.url();
    assert.equal((await frame.goto(sessionUrl, {waitUntil: 'domcontentloaded'})).status(), 200);
    await frame.waitForSelector('[contenteditable="true"]');
    assert.ok(!(await frame.$eval('body', node => node.innerText)).includes('Something went wrong'));
    // Exercise the actual public PTY API and native browser WebSocket. No
    // intercepted traffic or replacement server: this runs a real shell.
    const terminal = await frame.evaluate(async () => {
      const base = location.origin + '/admin/agent/opencode';
      const created = await fetch(base + '/pty', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({command: '/bin/sh', args: []}),
      });
      if (!created.ok) throw new Error('PTY create: ' + created.status);
      const pty = await created.json();
      try {
        const authorized = await fetch(base + '/pty/' + pty.id + '/connect-token', {
          method: 'POST', headers: {'x-opencode-ticket': '1'},
        });
        if (authorized.status !== 200) throw new Error('PTY ticket: ' + authorized.status);
        const {ticket} = await authorized.json();
        if (!ticket) throw new Error('PTY ticket missing');
        return await new Promise((resolve, reject) => {
          const url = new URL(base + '/pty/' + pty.id + '/connect');
          url.searchParams.set('ticket', ticket);
          url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
          const socket = new WebSocket(url);
          const timer = setTimeout(() => { socket.close(); reject(new Error('PTY output timed out')); }, 10000);
          let output = '';
          socket.onopen = () => socket.send("printf 'ABX_%s\\n' TERMINAL_OK\n");
          socket.onmessage = async event => {
            output += typeof event.data === 'string' ? event.data : await event.data.text();
            if (output.includes('ABX_TERMINAL_OK')) {
              clearTimeout(timer); socket.close(); resolve(output);
            }
          };
          socket.onerror = () => { clearTimeout(timer); reject(new Error('PTY WebSocket failed')); };
        });
      } finally { await fetch(base + '/pty/' + pty.id, {method: 'DELETE'}); }
    });
    assert.ok(terminal.includes('ABX_TERMINAL_OK'), terminal);
    assert.equal((await page.goto(config.url + '/add/', {waitUntil: 'domcontentloaded'})).status(), 200);
    console.log('AGENT_NAVIGATION_OK');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [str(browser_runtime["node_binary"]), "-e", script],
        input=json.dumps({"chrome": str(browser_runtime["chrome_binary"]), "url": server_url}),
        env={**os.environ, "NODE_PATH": browser_runtime["node_path"]},
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "AGENT_NAVIGATION_OK" in result.stdout


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
            "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser(username='agent-browser-test', password='test-password'); User.objects.create_user(username='agent-regular-test', password='test-password', is_staff=True)",
        ],
        cwd=config.data_dir,
        env=config.env,
    )
    assert user.returncode == 0, user.stderr or user.stdout
    process = start_archivebox_server(config.data_dir, port=port, env=config.env, log_name="agent-browser-server.log")
    try:
        yield url, config.data_dir, process
    finally:
        if process.poll() is None:
            stop_archivebox_process(process)


def _login_cookie(server_url, username="agent-browser-test"):
    session = requests.Session()
    login_url = server_url + "/admin/login/"
    page = session.get(login_url, timeout=10)
    assert page.status_code == 200
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.text)
    assert token is not None
    response = session.post(
        login_url,
        data={"username": username, "password": "test-password", "csrfmiddlewaretoken": token[1]},
        headers={"Referer": login_url},
        allow_redirects=False,
        timeout=10,
    )
    assert response.status_code == 302
    return "; ".join(f"{key}={value}" for key, value in session.cookies.items())


def test_agent_websocket_rejects_unauthorized_access(agent_server):
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    server_url, _, _ = agent_server
    admin_cookie = _login_cookie(server_url)
    regular_cookie = _login_cookie(server_url, "agent-regular-test")

    async def check_denials():
        for path, cookie, origin in (
            ("/admin/agent/opencode/pty/unknown/connect", "", server_url),
            ("/admin/agent/opencode/pty/unknown/connect", regular_cookie, server_url),
            ("/admin/agent/opencode/pty/unknown/connect", admin_cookie, "https://untrusted.example"),
            ("/admin/agent/opencode/pty/unknown/connect", admin_cookie, None),
            ("/health/", admin_cookie, server_url),
        ):
            with pytest.raises(InvalidStatus) as error:
                async with connect(
                    server_url.replace("http", "ws", 1) + path,
                    origin=origin,
                    additional_headers={"Cookie": cookie},
                    proxy=None,
                ):
                    pytest.fail("Unauthorized WebSocket was accepted")
            assert error.value.response.status_code == 403

    asyncio.run(check_denials())
    assert requests.get(server_url + "/health/", timeout=10).status_code == 200


@pytest.mark.parametrize(
    "mode,proxy_whitelist,use_cookie,http_status",
    [
        ("unsafe-onedomain-noadmin", "", True, 403),
        ("safe-onedomain-nojsreplay", "127.0.0.1/32", False, 200),
        ("safe-onedomain-nojsreplay", "192.0.2.0/24", False, 302),
    ],
)
def test_agent_websocket_matches_http_security_policy(agent_server, live_opencode, mode, proxy_whitelist, use_cookie, http_status):
    from urllib.parse import urlsplit
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    server_url, data_dir, process = agent_server
    cookie = _login_cookie(server_url)
    created = requests.post(
        server_url + "/admin/agent/opencode/pty",
        headers={"Cookie": cookie, "Origin": server_url},
        json={"command": "/bin/sh", "args": []},
        timeout=10,
    )
    assert created.status_code == 200
    pty_id = created.json()["id"]
    stop_archivebox_process(process)
    _set_archivebox_config(
        data_dir,
        f"SERVER_SECURITY_MODE={mode}",
        f"REVERSE_PROXY_WHITELIST={proxy_whitelist}",
        "REVERSE_PROXY_USER_HEADER=Remote-User",
    )
    restarted = start_archivebox_server(
        data_dir,
        port=urlsplit(server_url).port,
        env=live_opencode.config.env,
        log_name="agent-security-server.log",
    )
    headers = {"Cookie": cookie} if use_cookie else {"Remote-User": "agent-browser-test"}
    try:
        response = requests.get(server_url + "/admin/agent/opencode/global/health", headers=headers, allow_redirects=False, timeout=10)
        assert response.status_code == http_status

        async def check_socket():
            connection = connect(
                server_url.replace("http", "ws", 1) + f"/admin/agent/opencode/pty/{pty_id}/connect",
                origin=server_url,
                additional_headers=headers,
                proxy=None,
            )
            if http_status != 200:
                with pytest.raises(InvalidStatus) as error:
                    async with connection:
                        pytest.fail("Disabled control plane or untrusted proxy accepted a WebSocket")
                assert error.value.response.status_code == 403
                return
            async with connection as socket, asyncio.timeout(10):
                await socket.send("printf 'ABX_%s\\n' PROXY_OK\n")
                output = ""
                while "ABX_PROXY_OK" not in output:
                    chunk = await socket.recv()
                    output += chunk.decode() if isinstance(chunk, bytes) else chunk
                assert "ABX_PROXY_OK" in output

        asyncio.run(check_socket())
        assert requests.get(server_url + "/health/", timeout=10).status_code == 200
    finally:
        deleted = requests.delete(live_opencode.settings["origin"] + f"/pty/{pty_id}", timeout=10)
        assert deleted.status_code == 200
        stop_archivebox_process(restarted)


def test_agent_preserves_projects_and_survives_storage_failure(agent_server, browser_runtime):
    server_url, data_dir, _ = agent_server
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
