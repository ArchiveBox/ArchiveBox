#!/usr/bin/env python3
"""Browser-level security mode tests using the existing Node/Puppeteer runtime."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest
import requests

from .conftest import _ensure_puppeteer, _find_cached_chromium, _find_system_browser, run_python_cwd


PUPPETEER_PROBE_SCRIPT = """\
const fs = require("node:fs");
const puppeteer = require("puppeteer");

async function login(page, config) {
  const result = {
    reachable: false,
    succeeded: false,
    finalUrl: null,
    status: null,
    error: null,
  };

  try {
    const response = await page.goto(config.adminLoginUrl, {
      waitUntil: "networkidle2",
      timeout: 15000,
    });
    result.reachable = true;
    result.status = response ? response.status() : null;

    const usernameInput = await page.$('input[name="username"]');
    const passwordInput = await page.$('input[name="password"]');
    if (!usernameInput || !passwordInput) {
      result.finalUrl = page.url();
      return result;
    }

    await usernameInput.type(config.username);
    await passwordInput.type(config.password);
    await Promise.all([
      page.waitForNavigation({waitUntil: "networkidle2", timeout: 15000}),
      page.click('button[type="submit"], input[type="submit"]'),
    ]);

    result.finalUrl = page.url();
    result.succeeded = !page.url().includes("/admin/login/");
    return result;
  } catch (error) {
    result.error = String(error);
    result.finalUrl = page.url();
    return result;
  }
}

async function main() {
  const config = JSON.parse(fs.readFileSync(0, "utf8"));
  const browser = await puppeteer.launch({
    executablePath: config.chromePath,
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--disable-background-networking",
    ],
  });

  const loginPage = await browser.newPage();
  const loginResult = await login(loginPage, config);
  await loginPage.close();

  const page = await browser.newPage();
  const consoleMessages = [];
  const requestFailures = [];
  page.on("console", (message) => {
    consoleMessages.push({type: message.type(), text: message.text()});
  });
  page.on("pageerror", (error) => {
    consoleMessages.push({type: "pageerror", text: String(error)});
  });
  page.on("requestfailed", (request) => {
    requestFailures.push({
      url: request.url(),
      error: request.failure() ? request.failure().errorText : "unknown",
    });
  });

  const response = await page.goto(config.dangerousUrl, {
    waitUntil: "networkidle2",
    timeout: 15000,
  });

  await page.waitForFunction(
    () => window.__dangerousScriptRan !== true || window.__probeResults !== undefined,
    {timeout: 15000},
  );

  const pageState = await page.evaluate(() => ({
    href: location.href,
    scriptRan: window.__dangerousScriptRan === true,
    probeResults: window.__probeResults || null,
    bodyText: document.body ? document.body.innerText.slice(0, 600) : "",
  }));

  const output = {
    mode: config.mode,
    login: loginResult,
    dangerousPage: {
      status: response ? response.status() : null,
      finalUrl: page.url(),
      contentSecurityPolicy: response ? response.headers()["content-security-policy"] || null : null,
      archiveboxSecurityMode: response ? response.headers()["x-archivebox-security-mode"] || null : null,
    },
    pageState,
    consoleMessages,
    requestFailures,
  };

  console.log(JSON.stringify(output));
  await browser.close();
}

main().catch((error) => {
  console.error(String(error));
  process.exit(1);
});
"""


def _resolve_browser(shared_lib: Path) -> Path | None:
    env_browser = os.environ.get("CHROME_BINARY") or os.environ.get("CHROME_BIN")
    if env_browser:
        candidate = Path(env_browser).expanduser()
        if candidate.exists():
            return candidate

    cached = _find_cached_chromium(shared_lib)
    if cached and cached.exists():
        return cached

    system = _find_system_browser()
    if system and system.exists():
        return system

    which_candidates = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome")
    for binary in which_candidates:
        resolved = shutil.which(binary)
        if resolved:
            return Path(resolved)

    mac_candidates = (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    )
    for candidate in mac_candidates:
        if candidate.exists():
            return candidate

    return None


@pytest.fixture(scope="session")
def browser_runtime(tmp_path_factory):
    assert shutil.which("node") is not None, "Node.js is required for browser security tests"
    assert shutil.which("npm") is not None, "npm is required for browser security tests"

    shared_lib = tmp_path_factory.mktemp("archivebox_browser_lib")
    _ensure_puppeteer(shared_lib)

    browser = _resolve_browser(shared_lib)
    assert browser, "No Chrome/Chromium binary available for browser security tests"

    return {
        "node_modules_dir": shared_lib / "npm" / "node_modules",
        "chrome_binary": browser,
    }


def _seed_archive(data_dir: Path) -> dict[str, object]:
    script = textwrap.dedent(
        """
        import json
        import os
        from pathlib import Path
        from django.utils import timezone

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.core.settings")
        import django
        django.setup()

        from django.contrib.auth import get_user_model
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        User = get_user_model()
        admin, _ = User.objects.get_or_create(
            username="testadmin",
            defaults={"email": "admin@example.com", "is_staff": True, "is_superuser": True},
        )
        admin.set_password("testpassword")
        admin.save()

        snapshots = {}
        fixture_specs = (
            ("attacker", "https://attacker.example/entry", "Attacker Snapshot", "ATTACKER_SECRET"),
            ("victim", "https://victim.example/private", "Victim Snapshot", "VICTIM_SECRET"),
        )

        for slug, url, title, secret in fixture_specs:
            crawl = Crawl.objects.create(
                urls=url,
                created_by=admin,
                status=Crawl.StatusChoices.SEALED,
                retry_at=timezone.now(),
            )
            snapshot = Snapshot.objects.create(
                url=url,
                title=title,
                crawl=crawl,
                status=Snapshot.StatusChoices.SEALED,
                downloaded_at=timezone.now(),
            )
            output_dir = Path(snapshot.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "safe.json").write_text(
                json.dumps({"slug": slug, "secret": secret}),
                encoding="utf-8",
            )
            if slug == "attacker":
                (output_dir / "dangerous.html").write_text(
                    '''
                    <!doctype html>
                    <html>
                      <body>
                        <h1>Dangerous Replay Fixture</h1>
                        <script>
                          window.__dangerousScriptRan = true;
                          (async () => {
                            const params = new URLSearchParams(location.search);
                            const targets = {
                              own: params.get("own") || "safe.json",
                              victim: params.get("victim"),
                              admin: params.get("admin"),
                              api: params.get("api"),
                            };
                            const results = {};
                            for (const [label, url] of Object.entries(targets)) {
                              if (!url) continue;
                              try {
                                const response = await fetch(url, {credentials: "include"});
                                const text = await response.text();
                                results[label] = {
                                  ok: true,
                                  status: response.status,
                                  url: response.url,
                                  sample: text.slice(0, 120),
                                };
                              } catch (error) {
                                results[label] = {
                                  ok: false,
                                  error: String(error),
                                };
                              }
                            }
                            window.__probeResults = results;
                            const pre = document.createElement("pre");
                            pre.id = "probe-results";
                            pre.textContent = JSON.stringify(results);
                            document.body.appendChild(pre);
                          })().catch((error) => {
                            window.__probeResults = {fatal: String(error)};
                          });
                        </script>
                      </body>
                    </html>
                    ''',
                    encoding="utf-8",
                )
            snapshots[slug] = {
                "id": str(snapshot.id),
                "domain": snapshot.domain,
            }

        print(json.dumps({
            "username": "testadmin",
            "password": "testpassword",
            "snapshots": snapshots,
        }))
        """,
    )
    stdout, stderr, returncode = run_python_cwd(script, cwd=data_dir, timeout=120)
    assert returncode == 0, stderr
    return json.loads(stdout.strip())


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_http(
    port: int,
    host: str,
    timeout: float = 30.0,
    process: subprocess.Popen[str] | None = None,
) -> None:
    deadline = time.time() + timeout
    last_error = "server did not answer"
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            raise AssertionError(f"Server exited before becoming ready with code {process.returncode}")
        try:
            response = requests.get(
                f"http://127.0.0.1:{port}/",
                headers={"Host": host},
                timeout=2,
                allow_redirects=False,
            )
            if response.status_code < 500:
                return
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting for {host}: {last_error}")


def _start_server(data_dir: Path, *, mode: str, port: int) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.pop("DATA_DIR", None)
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "LISTEN_HOST": f"archivebox.localhost:{port}",
            "ALLOWED_HOSTS": "*",
            "CSRF_TRUSTED_ORIGINS": f"http://archivebox.localhost:{port},http://admin.archivebox.localhost:{port}",
            "SERVER_SECURITY_MODE": mode,
            "USE_COLOR": "False",
            "SHOW_PROGRESS": "False",
            "SAVE_ARCHIVEDOTORG": "False",
            "SAVE_TITLE": "False",
            "SAVE_FAVICON": "False",
            "SAVE_WGET": "False",
            "SAVE_WARC": "False",
            "SAVE_PDF": "False",
            "SAVE_SCREENSHOT": "False",
            "SAVE_DOM": "False",
            "SAVE_SINGLEFILE": "False",
            "SAVE_READABILITY": "False",
            "SAVE_MERCURY": "False",
            "SAVE_GIT": "False",
            "SAVE_YTDLP": "False",
            "SAVE_HEADERS": "False",
            "SAVE_HTMLTOTEXT": "False",
            "USE_CHROME": "False",
        },
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "archivebox", "server", "--debug", "--nothreading", f"127.0.0.1:{port}"],
        cwd=data_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        _wait_for_http(port, f"archivebox.localhost:{port}", process=process)
    except AssertionError as exc:
        server_log = _stop_server(process)
        raise AssertionError(f"{exc}\n\nSERVER LOG:\n{server_log}") from exc
    return process


def _stop_server(process: subprocess.Popen[str]) -> str:
    try:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, _ = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, _ = process.communicate(timeout=5)
        else:
            stdout, _ = process.communicate(timeout=5)
    except ProcessLookupError:
        stdout, _ = process.communicate(timeout=5)
    return stdout


def _build_probe_config(mode: str, port: int, fixture: dict[str, object], runtime: dict[str, Path]) -> dict[str, str]:
    snapshots = fixture["snapshots"]
    attacker = snapshots["attacker"]
    victim = snapshots["victim"]
    base_origin = f"http://archivebox.localhost:{port}"
    attacker_id = attacker["id"]
    victim_id = victim["id"]

    if mode == "safe-subdomains-fullreplay":
        attacker_origin = f"http://{attacker_id}.archivebox.localhost:{port}"
        victim_url = f"http://{victim_id}.archivebox.localhost:{port}/safe.json"
        dangerous_base = f"{attacker_origin}/dangerous.html"
        admin_origin = f"http://admin.archivebox.localhost:{port}"
    else:
        attacker_origin = base_origin
        victim_url = f"{base_origin}/snapshot/{victim_id}/safe.json"
        dangerous_base = f"{base_origin}/snapshot/{attacker_id}/dangerous.html"
        admin_origin = base_origin

    query = urlencode(
        {
            "own": "safe.json",
            "victim": victim_url,
            "admin": f"{admin_origin}/admin/",
            "api": f"{admin_origin}/api/v1/docs",
        },
    )

    return {
        "mode": mode,
        "chromePath": str(runtime["chrome_binary"]),
        "adminLoginUrl": f"{admin_origin}/admin/login/",
        "dangerousUrl": f"{dangerous_base}?{query}",
        "username": fixture["username"],
        "password": fixture["password"],
    }


def _run_browser_probe(
    data_dir: Path,
    runtime: dict[str, Path],
    mode: str,
    fixture: dict[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    port = _get_free_port()
    process = _start_server(data_dir, mode=mode, port=port)
    probe_path = tmp_path / "server_security_probe.js"
    probe_path.write_text(PUPPETEER_PROBE_SCRIPT, encoding="utf-8")
    probe_config = _build_probe_config(mode, port, fixture, runtime)

    env = os.environ.copy()
    env["NODE_PATH"] = str(runtime["node_modules_dir"])
    env["NODE_MODULES_DIR"] = str(runtime["node_modules_dir"])
    env["CHROME_BINARY"] = str(runtime["chrome_binary"])
    env["USE_COLOR"] = "False"

    try:
        result = subprocess.run(
            ["node", str(probe_path)],
            cwd=data_dir,
            env=env,
            input=json.dumps(probe_config),
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        server_log = _stop_server(process)

    assert result.returncode == 0, f"{result.stderr}\n\nSERVER LOG:\n{server_log}"
    return json.loads(result.stdout.strip())


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (
            "safe-subdomains-fullreplay",
            {
                "login_succeeds": True,
                "script_ran": True,
                "victim_ok": False,
                "admin_ok": False,
                "admin_status": None,
                "api_ok": False,
                "api_status": None,
                "csp_contains": None,
            },
        ),
        (
            "safe-onedomain-nojsreplay",
            {
                "login_succeeds": True,
                "script_ran": False,
                "victim_ok": None,
                "admin_ok": None,
                "admin_status": None,
                "api_ok": None,
                "api_status": None,
                "csp_contains": "sandbox",
            },
        ),
        (
            "unsafe-onedomain-noadmin",
            {
                "login_succeeds": False,
                "login_status": 403,
                "script_ran": True,
                "victim_ok": True,
                "victim_status": 200,
                "admin_ok": True,
                "admin_status": 403,
                "api_ok": True,
                "api_status": 403,
                "csp_contains": None,
            },
        ),
        (
            "danger-onedomain-fullreplay",
            {
                "login_succeeds": True,
                "script_ran": True,
                "victim_ok": True,
                "victim_status": 200,
                "admin_ok": True,
                "admin_status": 200,
                "api_ok": True,
                "api_status": 200,
                "csp_contains": None,
            },
        ),
    ],
)
def test_server_security_modes_in_chrome(
    initialized_archive: Path,
    browser_runtime,
    tmp_path: Path,
    mode: str,
    expected: dict[str, object],
) -> None:
    fixture = _seed_archive(initialized_archive)
    result = _run_browser_probe(initialized_archive, browser_runtime, mode, fixture, tmp_path)

    login = result["login"]
    dangerous_page = result["dangerousPage"]
    page_state = result["pageState"]
    probe_results = page_state["probeResults"] or {}
    console_texts = [entry["text"] for entry in result["consoleMessages"]]

    assert dangerous_page["status"] == 200
    assert dangerous_page["archiveboxSecurityMode"] == mode
    assert page_state["scriptRan"] is expected["script_ran"]
    assert login["succeeded"] is expected["login_succeeds"]

    login_status = expected.get("login_status")
    if login_status is not None:
        assert login["status"] == login_status

    csp_contains = expected.get("csp_contains")
    if csp_contains:
        csp = dangerous_page["contentSecurityPolicy"] or ""
        assert csp_contains in csp
    else:
        assert dangerous_page["contentSecurityPolicy"] is None

    if mode == "safe-subdomains-fullreplay":
        assert probe_results["own"]["ok"] is True
        assert probe_results["own"]["status"] == 200
        assert "ATTACKER_SECRET" in probe_results["own"]["sample"]
        assert probe_results["victim"]["ok"] is expected["victim_ok"]
        assert probe_results["admin"]["ok"] is expected["admin_ok"]
        assert probe_results["api"]["ok"] is expected["api_ok"]
        assert any("CORS policy" in text for text in console_texts)
        return

    if mode == "safe-onedomain-nojsreplay":
        assert probe_results == {}
        assert "Dangerous Replay Fixture" in page_state["bodyText"]
        assert any("Blocked script execution" in text for text in console_texts)
        return

    assert probe_results["own"]["ok"] is True
    assert probe_results["own"]["status"] == 200
    assert "ATTACKER_SECRET" in probe_results["own"]["sample"]
    assert probe_results["victim"]["ok"] is expected["victim_ok"]
    assert probe_results["victim"]["status"] == expected["victim_status"]
    assert "VICTIM_SECRET" in probe_results["victim"]["sample"]
    assert probe_results["admin"]["ok"] is expected["admin_ok"]
    assert probe_results["admin"]["status"] == expected["admin_status"]
    assert probe_results["api"]["ok"] is expected["api_ok"]
    assert probe_results["api"]["status"] == expected["api_status"]

    if mode == "unsafe-onedomain-noadmin":
        assert "control plane disabled" in probe_results["admin"]["sample"].lower()
        assert "control plane disabled" in probe_results["api"]["sample"].lower()
    elif mode == "danger-onedomain-fullreplay":
        assert "ArchiveBox" in probe_results["admin"]["sample"]
        assert "swagger" in probe_results["api"]["sample"].lower()
