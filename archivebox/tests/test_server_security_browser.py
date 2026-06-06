#!/usr/bin/env python3
"""Browser-level security mode tests using the existing Node/Puppeteer runtime."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

from .conftest import _find_cached_chrome, _find_system_browser, run_python_cwd
from .conftest import (
    cli_env,
    get_free_port,
    run_archivebox_cmd,
    start_archivebox_server as start_daemon_server,
    stop_archivebox_process,
    stop_server as stop_daemon_server,
    wait_for_http,
)


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


PUPPETEER_WACZ_PREVIEW_SCRIPT = """\
const fs = require("node:fs");
const puppeteer = require("puppeteer");

function isDescendantOf(frame, ancestor) {
  let parent = frame.parentFrame();
  while (parent) {
    if (parent === ancestor) return true;
    parent = parent.parentFrame();
  }
  return false;
}

async function frameText(frame) {
  try {
    return await frame.evaluate(() => {
      const body = document.body ? document.body.innerText : "";
      const root = document.documentElement ? document.documentElement.innerText : "";
      return body || root || "";
    });
  } catch (_error) {
    return "";
  }
}

async function findPreviewText(page, expectedText, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastState = [];
  while (Date.now() < deadline) {
    const frames = page.frames();
    const previewFrame = frames.find((frame) => {
      const url = frame.url();
      return url.includes("/archivewebpage/archivewebpage.wacz") && url.includes("preview=1");
    });

    lastState = [];
    for (const frame of frames) {
      const text = await frameText(frame);
      lastState.push({
        name: frame.name(),
        url: frame.url(),
        isPreview: frame === previewFrame,
        underPreview: previewFrame ? isDescendantOf(frame, previewFrame) : false,
        textSample: text.slice(0, 240),
      });
      if (previewFrame && (frame === previewFrame || isDescendantOf(frame, previewFrame)) && text.includes(expectedText)) {
        return {
          matched: true,
          previewUrl: previewFrame.url(),
          matchedFrameUrl: frame.url(),
          matchedFrameName: frame.name(),
          textSample: text.slice(0, 400),
        };
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return {matched: false, frames: lastState};
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

  const response = await page.goto(config.detailUrl, {
    waitUntil: "domcontentloaded",
    timeout: 30000,
  });
  const previewResult = await findPreviewText(page, config.expectedText, 60000);

  console.log(JSON.stringify({
    detailUrl: config.detailUrl,
    status: response ? response.status() : null,
    finalUrl: page.url(),
    previewResult,
    consoleMessages,
    requestFailures,
  }));
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

    system = _find_system_browser()
    if system and system.exists():
        return system

    cached = _find_cached_chrome(shared_lib)
    if cached and cached.exists():
        return cached

    which_candidates = ("chromium", "chromium-browser")
    for binary in which_candidates:
        resolved = shutil.which(binary)
        if resolved:
            return Path(resolved)

    mac_candidates = (
        Path("/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    )
    for candidate in mac_candidates:
        if candidate.exists():
            return candidate

    return None


@pytest.fixture
def browser_runtime(initialized_archive: Path):
    assert shutil.which("node") is not None, "Node.js is required for browser security tests"

    shared_lib = initialized_archive / "lib"
    env = cli_env(
        ABXPKG_INSTALL_TIMEOUT="900",
        ABXPKG_MIN_RELEASE_AGE="0",
        LIB_DIR=str(shared_lib),
        ABXPKG_LIB_DIR=str(shared_lib),
        CHROME_HEADLESS="True",
        CHROME_SANDBOX="False",
        CHROME_ISOLATION="snapshot",
    )
    env.pop("CHROME_BINARY", None)
    install_result = run_archivebox_cmd(
        ["install", "chrome"],
        cwd=initialized_archive,
        env=env,
        timeout=900,
    )
    assert install_result.returncode == 0, install_result.stderr or install_result.stdout

    browser = _resolve_browser(shared_lib)
    assert browser, "No Chrome/Chromium binary available for browser security tests"

    return {
        "lib_dir": shared_lib,
        "node_modules_dir": shared_lib / "pnpm" / "packages" / "chrome" / "node_modules",
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
    port = get_free_port()
    server_env = os.environ.copy()
    server_env.pop("DATA_DIR", None)
    server_env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "BIND_ADDR": f"127.0.0.1:{port}",
            "BASE_URL": f"http://archivebox.localhost:{port}",
            "ALLOWED_HOSTS": "*",
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
    process = run_archivebox_cmd(
        ["server", "--debug", "--nothreading", f"127.0.0.1:{port}"],
        cwd=data_dir,
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        wait=False,
    )
    try:
        wait_for_http(port, f"archivebox.localhost:{port}", process=process)
    except AssertionError as exc:
        server_log = stop_archivebox_process(process)
        raise AssertionError(f"{exc}\n\nSERVER LOG:\n{server_log}") from exc

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
        server_log = stop_archivebox_process(process)

    assert result.returncode == 0, f"{result.stderr}\n\nSERVER LOG:\n{server_log}"
    return json.loads(result.stdout.strip())


def _wait_for_archivewebpage_capture(data_dir: Path, url: str, timeout: float = 300.0) -> dict[str, str]:
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    deadline = time.time() + timeout
    last_state = {}
    while time.time() < deadline:
        with use_archivebox_db(data_dir):
            snapshot = Snapshot.objects.filter(url=url).order_by("-created_at").first()
            if snapshot is None:
                last_state = {"snapshot": "missing"}
            else:
                result = (
                    ArchiveResult.objects.filter(snapshot=snapshot, plugin="archivewebpage")
                    .order_by("-created_at")
                    .values("status", "output_files", "output_str")
                    .first()
                )
                wacz_path = Path(snapshot.output_dir) / "archivewebpage" / "archivewebpage.wacz"
                last_state = {
                    "snapshot_id": str(snapshot.id),
                    "snapshot_status": str(snapshot.status),
                    "result": str(result),
                    "wacz_path": str(wacz_path),
                    "wacz_exists": str(wacz_path.is_file()),
                }
                if (
                    snapshot.status == Snapshot.StatusChoices.SEALED
                    and result is not None
                    and result["status"] == ArchiveResult.StatusChoices.SUCCEEDED
                    and wacz_path.is_file()
                ):
                    return {
                        "snapshot_id": str(snapshot.id),
                        "wacz_path": str(wacz_path),
                    }
        time.sleep(2)
    raise AssertionError(f"timed out waiting for archivewebpage capture: {last_state}")


def _run_wacz_preview_probe(data_dir: Path, runtime: dict[str, Path], detail_url: str, tmp_path: Path) -> dict[str, object]:
    probe_path = tmp_path / "wacz_preview_probe.js"
    probe_path.write_text(PUPPETEER_WACZ_PREVIEW_SCRIPT, encoding="utf-8")

    env = os.environ.copy()
    env["NODE_PATH"] = str(runtime["node_modules_dir"])
    env["NODE_MODULES_DIR"] = str(runtime["node_modules_dir"])
    env["CHROME_BINARY"] = str(runtime["chrome_binary"])
    env["USE_COLOR"] = "False"

    result = subprocess.run(
        ["node", str(probe_path)],
        cwd=data_dir,
        env=env,
        input=json.dumps(
            {
                "chromePath": str(runtime["chrome_binary"]),
                "detailUrl": detail_url,
                "expectedText": "This domain is for use in documentation examples",
            },
        ),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.timeout(600)
def test_archivewebpage_wacz_preview_serves_real_capture_frame(initialized_archive: Path, browser_runtime, tmp_path: Path) -> None:
    from archivebox.core.routes_util import get_snapshot_subdomain

    url = "https://example.com"
    port = get_free_port()
    env = cli_env(
        port=port,
        PLUGINS="archivewebpage",
        BASE_URL=f"http://archivebox.localhost:{port}",
        URL_ALLOWLIST="",
        PUBLIC_INDEX="True",
        PUBLIC_ADD_VIEW="True",
        SERVER_SECURITY_MODE="safe-subdomains-fullreplay",
        USE_CHROME="True",
        CHROME_BINARY=str(browser_runtime["chrome_binary"]),
        CHROME_HEADLESS="True",
        CHROME_SANDBOX="False",
        CHROME_ISOLATION="snapshot",
        ARCHIVEWEBPAGE_ENABLED="True",
        ARCHIVEWEBPAGE_TIMEOUT="90",
        TIMEOUT="90",
    )
    env["LIB_DIR"] = str(browser_runtime["lib_dir"])
    env["ABXPKG_LIB_DIR"] = str(browser_runtime["lib_dir"])
    env["NODE_PATH"] = str(browser_runtime["node_modules_dir"])
    env["NODE_MODULES_DIR"] = str(browser_runtime["node_modules_dir"])
    env["CHROME_EXTENSIONS_DIR"] = str(
        browser_runtime["lib_dir"] / "chromewebstore" / "extensions",
    )

    try:
        install_result = run_archivebox_cmd(
            ["install", "archivewebpage"],
            cwd=initialized_archive,
            env=env,
            timeout=600,
        )
        assert install_result.returncode == 0, (
            f"archivebox install archivewebpage failed:\nSTDOUT:\n{install_result.stdout}\nSTDERR:\n{install_result.stderr}"
        )

        start_daemon_server(initialized_archive, env=env, port=port)
        wait_for_http(port, host=f"archivebox.localhost:{port}", path="/")
        _cmd_result = run_archivebox_cmd(
            ["add", "--bg", "--depth=0", "--max-urls=1", "--plugins=archivewebpage", url],
            cwd=initialized_archive,
            env=env,
            timeout=120,
        )
        stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        assert returncode == 0, f"archivebox add --bg failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

        capture = _wait_for_archivewebpage_capture(initialized_archive, url, timeout=360)
        snapshot_host = f"{get_snapshot_subdomain(capture['snapshot_id'])}.archivebox.localhost:{port}"
        detail_url = f"http://{snapshot_host}/#archivewebpage/archivewebpage.wacz"
        result = _run_wacz_preview_probe(initialized_archive, browser_runtime, detail_url, tmp_path)
    finally:
        stop_daemon_server(initialized_archive)

    assert result["status"] == 200
    assert result["previewResult"]["matched"], json.dumps(result, indent=2)
    assert "/archivewebpage/archivewebpage.wacz" in result["previewResult"]["previewUrl"]
    assert result["previewResult"]["matchedFrameUrl"] != result["finalUrl"]
