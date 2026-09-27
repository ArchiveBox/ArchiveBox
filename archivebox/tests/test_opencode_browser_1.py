"""Exercise the real agent wrapper with Chromium's native storage failures."""

import json
import os
import re
import subprocess

import pytest
import requests

from .conftest import get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process
from .test_opencode_agent_1 import _set_archivebox_config
from .test_opencode_agent_1 import installed_opencode as installed_opencode
from .test_opencode_agent_1 import live_opencode as live_opencode
from .test_opencode_agent_1 import opencode_archive_config as opencode_archive_config
from .test_server_security_browser import browser_runtime as browser_runtime


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def agent_server(installed_opencode, browser_runtime, request):
    port = get_free_port()
    mode, subdomains = getattr(request, "param", ("safe-onedomain-nojsreplay", False))
    base_url = f"http://archivebox.localhost:{port}" if subdomains else f"http://localhost:{port}"
    url = f"http://admin.archivebox.localhost:{port}" if subdomains else base_url
    config = installed_opencode.config
    _set_archivebox_config(
        config.data_dir,
        f"BASE_URL={base_url}",
        f"SERVER_SECURITY_MODE={mode}",
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


@pytest.mark.parametrize(
    "agent_server",
    [
        ("safe-onedomain-nojsreplay", False),
        ("safe-subdomains-fullreplay", True),
        ("danger-onedomain-fullreplay", False),
        ("auto", False),
        ("auto", True),
    ],
    indirect=True,
)
def test_agent_navigation_stays_inside_mount(agent_server, browser_runtime):
    server_url, data_dir, _ = agent_server
    filename = "proxy acceptance #é.txt"
    (data_dir / filename).write_text("Proxy file read: café", encoding="utf-8")
    script = r"""
const assert = require('node:assert/strict');
const puppeteer = require('puppeteer');
const config = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
(async () => {
  const browser = await puppeteer.launch({executablePath: config.chrome, headless: true,
    args: ['--no-sandbox', '--disable-frame-rate-limit']});
  try {
    const page = await browser.newPage();
    const escapedRequests = [];
    page.on('request', request => {
      const url = new URL(request.url());
      if (request.frame()?.parentFrame() && url.origin === config.url &&
          !url.pathname.startsWith('/admin/agent/opencode/')) {
        escapedRequests.push(request.method() + ' ' + url.pathname);
      }
    });
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
    const initialSessionUrl = frame.url();
    await frame.locator('::-p-aria(New session[role="button"])').click();
    await frame.waitForFunction(previous => location.href !== previous, {}, initialSessionUrl);
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
    // Real JSON methods, encoded file paths, and both SSE subscriptions must
    // work on the admin origin in every routing mode, without installing or
    // authenticating a paid model provider during the test.
    const requests = await frame.evaluate(async filename => {
      const base = location.origin + '/admin/agent/opencode';
      const json = async (path, method = 'GET', body) => {
        const response = await fetch(base + path, {
          method, headers: {'Content-Type': 'application/json'},
          ...(body === undefined ? {} : {body: JSON.stringify(body)}),
        });
        if (!response.ok) throw new Error(method + ' ' + path + ': ' + response.status);
        if (!response.headers.get('Content-Type')?.includes('application/json')) {
          throw new Error('Non-JSON response: ' + path);
        }
        return response.json();
      };
      const providers = await json('/provider');
      const auth = await json('/provider/auth');
      const file = await json('/file/content?path=' + encodeURIComponent(filename));
      const session = await json('/session', 'POST', {title: 'Proxy request verification'});
      let renamed;
      try {
        renamed = await json('/session/' + session.id, 'PATCH', {title: 'Proxy: café & # symbols'});
        const readback = await json('/session/' + session.id);
        if (readback.title !== renamed.title) throw new Error('Session mutation was not persisted');
      } finally { await json('/session/' + session.id, 'DELETE'); }
      const streams = [];
      for (const path of ['/event', '/global/event']) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5000);
        try {
          const response = await fetch(base + path, {signal: controller.signal});
          if (!response.ok || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
            throw new Error('Invalid event stream: ' + path);
          }
          const reader = response.body.getReader();
          const first = await reader.read();
          streams.push(new TextDecoder().decode(first.value));
          await reader.cancel();
        } finally { clearTimeout(timeout); controller.abort(); }
      }
      return {providers: providers.all.map(provider => provider.id), auth, file, renamed, streams};
    }, config.filename);
    for (const provider of ['openai', 'anthropic']) assert.ok(requests.providers.includes(provider), provider);
    assert.ok(requests.auth.openai.some(method => method.type === 'oauth'));
    assert.equal(requests.file.content, 'Proxy file read: café');
    assert.equal(requests.renamed.title, 'Proxy: café & # symbols');
    for (const event of requests.streams) assert.ok(event.includes('server.connected'), event);
    for (const provider of ['OpenAI', 'Anthropic']) {
      await frame.locator('[data-action="prompt-model"]').click();
      await frame.locator('::-p-aria(' + provider + '[role="button"])').click();
      if (provider === 'OpenAI') {
        await frame.waitForSelector('::-p-aria(ChatGPT Pro/Plus Headless[role="button"])');
        await frame.waitForSelector('::-p-aria(ChatGPT Pro/Plus Browser[role="button"])');
        await frame.locator('::-p-aria(API key Browser[role="button"])').click();
      }
      const input = await frame.waitForSelector('::-p-aria(' + provider + ' API key[role="textbox"])');
      assert.equal(await input.evaluate(node => node.value), '');
      await frame.waitForSelector('::-p-aria(Continue[role="button"])');
      await frame.locator('::-p-aria(Close[role="button"])').click();
    }
    // Submit a real shell command from a fresh draft. This exercises draft
    // promotion and the shell API without needing a paid model or API key.
    await frame.locator('::-p-aria(New session[role="button"])').click();
    await frame.waitForFunction(() => location.pathname.endsWith('/new-session'));
    await (await frame.waitForSelector('[contenteditable="true"]')).focus();
    const modifier = await page.evaluate(() => navigator.platform.includes('Mac') ? 'Meta' : 'Control');
    await page.keyboard.down(modifier);
    await page.keyboard.down('Shift');
    await page.keyboard.press('x');
    await page.keyboard.up('Shift');
    await page.keyboard.up(modifier);
    await page.keyboard.type('printf ABX_DRAFT_SHELL_OK');
    await frame.locator('::-p-aria(Send[role="button"])').click();
    await frame.waitForFunction(() => /\/session\/ses_/.test(location.pathname));
    assert.ok(new URL(frame.url()).pathname.startsWith('/admin/agent/opencode/'), frame.url());
    await frame.waitForFunction(async () => {
      const sessionID = location.pathname.match(/\/session\/(ses_[^/]+)/)[1];
      const response = await fetch('/admin/agent/opencode/session/' + sessionID + '/message');
      if (!response.ok) throw new Error('Shell message readback: ' + response.status);
      const messages = await response.json();
      return messages.some(message => message.parts.some(part =>
        part.type === 'tool' && part.state.status === 'completed' &&
        part.state.output.trim() === 'ABX_DRAFT_SHELL_OK'));
    }, {polling: 250});
    // The tabbed layout's own route parser must recognize mounted sessions.
    // Otherwise Home incorrectly appears selected and clicking it does nothing.
    const shellSessionUrl = frame.url();
    const home = await frame.waitForSelector('[aria-label="Home"]');
    assert.equal(await home.evaluate(node => node.getAttribute('aria-pressed')), 'false');
    await home.click();
    await frame.waitForFunction(() => location.pathname.replace(/\/+$/, '') === '/admin/agent/opencode');
    assert.equal(await home.evaluate(node => node.getAttribute('aria-pressed')), 'true');
    await home.click();
    await frame.waitForFunction(expected => location.href === expected, {}, shellSessionUrl);
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
    assert.deepEqual(escapedRequests, [], 'OpenCode requests must stay inside its proxy mount');
    assert.equal((await page.goto(config.url + '/add/', {waitUntil: 'domcontentloaded'})).status(), 200);
    console.log('AGENT_NAVIGATION_OK');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [str(browser_runtime["node_binary"]), "-e", script],
        input=json.dumps({"chrome": str(browser_runtime["chrome_binary"]), "url": server_url, "filename": filename}),
        env={**os.environ, "NODE_PATH": browser_runtime["node_path"]},
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "AGENT_NAVIGATION_OK" in result.stdout
