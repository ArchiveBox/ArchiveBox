#!/usr/bin/env python3
"""
Tests for archivebox persona command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_persona_open_background_returns_ready_and_reuses_browser(initialized_archive, cached_abxpkg_lib_dir, httpserver):
    import json
    import os
    import subprocess
    from pathlib import Path

    import psutil

    from archivebox.tests.conftest import resolve_abxpkg_chrome_env
    from archivebox.plugins.discovery import get_plugin_catalog

    browser_env = resolve_abxpkg_chrome_env(cached_abxpkg_lib_dir)
    browser_env.update(ABXPKG_LIB_DIR=str(cached_abxpkg_lib_dir), CHROME_SANDBOX="false")
    persona_dir = initialized_archive / "personas" / "Background test"
    persona_dir.mkdir(parents=True)
    (persona_dir / "auth.json").write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "selected_persona",
                        "value": "selected",
                        "domain": "127.0.0.1",
                        "path": "/",
                        "httpOnly": True,
                        "secure": False,
                        "sameSite": "Lax",
                        "expires": -1,
                    },
                ],
                "origins": [],
            },
        ),
    )
    browser_env.update(
        CHROME_USER_DATA_DIR=str(initialized_archive / "unrelated-profile"),
        AUTH_STORAGE_FILE=str(initialized_archive / "unrelated-auth.json"),
        COOKIES_FILE=str(initialized_archive / "unrelated-cookies.txt"),
        ABX_RUNTIME="abx-dl",
    )
    httpserver.expect_request("/").respond_with_data("<title>Background persona ready</title>", content_type="text/html")
    launched = run_archivebox_cmd(
        ["persona", "open", "Background test", "--headless", "--background"],
        cwd=initialized_archive,
        env=browser_env,
        timeout=90,
    )
    assert launched.returncode == 0, launched.stderr + launched.stdout
    result = json.loads(launched.stdout.strip().splitlines()[-1])
    browser = psutil.Process(result["browser_pid"])
    owner = browser.parent()
    browser_dir = initialized_archive / "personas" / "Background test" / ".browser"
    try:
        endpoint = (browser_dir / "cdp_url.txt").read_text().strip()
        browser_pid = (browser_dir / "chrome.pid").read_text().strip()
        assert browser.is_running()
        assert f"--user-data-dir={persona_dir / 'chrome_profile'}" in browser.cmdline()
        assert "Browser ready for persona Background test" in Path(result["log"]).read_text()
        probe = subprocess.run(
            [
                browser_env["NODE_BINARY"],
                "-e",
                """const puppeteer = require(process.argv[1]);
(async () => {
  const browser = await puppeteer.connect({browserWSEndpoint: process.argv[2]});
  try {
    const page = (await browser.pages())[0];
    await page.goto(process.argv[3]);
    console.log(await page.title());
    console.log(JSON.stringify(await browser.cookies()));
  } finally { await browser.disconnect(); }
})().catch(error => { console.error(error); process.exit(1); });""",
                str(cached_abxpkg_lib_dir / "pnpm/packages/chrome/node_modules/puppeteer"),
                endpoint,
                httpserver.url_for("/"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert probe.returncode == 0, probe.stderr
        assert "Background persona ready" in probe.stdout
        cookies = json.loads(probe.stdout.strip().splitlines()[-1])
        assert next(cookie for cookie in cookies if cookie["name"] == "selected_persona")["value"] == "selected"
        assert (browser_dir / "tabs.json").exists()
        command = get_plugin_catalog().find_command("browser-export-state")
        exported_auth = initialized_archive / "live-auth.json"
        exported = subprocess.run(
            [str(command.path), *command.args],
            input=json.dumps(
                {
                    "config": {**browser_env, "CHROME_CDP_URL": "http://127.0.0.1:1"},
                    "user_data_dir": str(initialized_archive / "missing-profile"),
                    "cdp_url": endpoint,
                    "auth_output_file": str(exported_auth),
                },
            ),
            env={**os.environ, "CHROME_CDP_URL": "http://127.0.0.1:1"},
            text=True,
            capture_output=True,
            timeout=90,
        )
        assert exported.returncode == 0, exported.stderr
        assert (
            next(cookie for cookie in json.loads(exported_auth.read_text())["cookies"] if cookie["name"] == "selected_persona")["value"]
            == "selected"
        )
        assert browser.is_running()
        reused = run_archivebox_cmd(
            ["persona", "open", "Background test", "--headless", "--background"],
            cwd=initialized_archive,
            env=browser_env,
            timeout=90,
        )
        assert reused.returncode == 0, reused.stderr + reused.stdout
        assert (browser_dir / "cdp_url.txt").read_text().strip() == endpoint
        assert (browser_dir / "chrome.pid").read_text().strip() == browser_pid
        assert browser.is_running()
        open_command = get_plugin_catalog().find_command("browser-open")
        argv_reuse = subprocess.run(
            [
                str(open_command.path),
                *open_command.args,
                "--persona-dir",
                str(persona_dir),
                "--persona-name",
                "Background test",
                "--headless",
            ],
            env={**os.environ, **browser_env, "AUTH_STORAGE_FILE": str(persona_dir / "auth.json"), "COOKIES_FILE": ""},
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert argv_reuse.returncode == 0, argv_reuse.stderr
        ready = json.loads(argv_reuse.stdout.strip().splitlines()[-1])
        assert ready["ready"] is True
        assert str(ready["browser_pid"]) == browser_pid
        assert ready["cdp_url"] == endpoint
        assert browser.is_running()
    finally:
        browser.terminate()
        browser.wait(timeout=15)
        owner.wait(timeout=15)


def test_persona_open_background_reports_launch_failure(initialized_archive, cached_abxpkg_lib_dir):
    from archivebox.tests.conftest import resolve_abxpkg_chrome_env

    browser_env = resolve_abxpkg_chrome_env(cached_abxpkg_lib_dir)
    browser_env.update(ABXPKG_LIB_DIR=str(cached_abxpkg_lib_dir), CHROME_SANDBOX="false")
    # A real filesystem conflict prevents the browser owner acquiring its lock.
    browser_dir = initialized_archive / "personas" / "Blocked" / ".browser"
    (browser_dir / "launch.lock").mkdir(parents=True)
    result = run_archivebox_cmd(
        ["persona", "open", "Blocked", "--headless", "--background"],
        cwd=initialized_archive,
        env=browser_env,
        timeout=90,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Timeout acquiring lock: launch.lock" in result.stderr
    assert ".log" in result.stderr
    assert not (browser_dir / "cdp_url.txt").exists()


def test_persona_help_runs_successfully(tmp_path):
    """The persona command should be registered and expose help."""

    result = run_archivebox_cmd(["persona", "--help"])

    assert result.returncode == 0
    assert "persona" in result.stdout.lower()
    assert "list" in result.stdout


def test_persona_create_permissions_preserves_existing_persona(initialized_archive):
    from archivebox.tests.conftest import run_python_cwd

    result = run_archivebox_cmd(["persona", "create", "--permissions=private", "host-profile"], cwd=initialized_archive)
    assert result.returncode == 0, result.stderr
    existing = run_archivebox_cmd(["persona", "create", "--permissions=public", "host-profile"], cwd=initialized_archive)
    assert existing.returncode == 0, existing.stderr
    stdout, stderr, returncode = run_python_cwd(
        "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings'); "
        "import django; django.setup(); from archivebox.personas.models import Persona; "
        "p = Persona.objects.get(name='host-profile'); assert p.permissions == 'private'; print('private')",
        cwd=initialized_archive,
    )
    assert returncode == 0, stderr
    assert "private" in stdout


def test_persona_import_missing_source_is_actionable_and_does_not_create(initialized_archive, tmp_path):
    result = run_archivebox_cmd(
        ["persona", "create", "--import=brave", "--source", str(tmp_path / "missing"), "broken"],
        cwd=initialized_archive,
    )
    assert result.returncode == 1
    assert "does not exist" in result.stderr
    listed = run_archivebox_cmd(["persona", "list", "--name=broken"], cwd=initialized_archive)
    assert listed.returncode == 0
    assert not listed.stdout.strip()
    assert not (initialized_archive / "personas" / "broken").exists()


def test_persona_import_real_browser_session(initialized_archive, tmp_path, httpserver):
    """Import an actual Chromium-created session and archive its private page."""
    import hashlib
    import json
    import os
    import shlex
    import subprocess
    from pathlib import Path

    from werkzeug.wrappers import Response
    from archivebox.tests.conftest import resolve_abxpkg_chrome_env
    from archivebox.plugins.discovery import get_plugin_catalog

    browser_env = resolve_abxpkg_chrome_env(tmp_path / "lib")
    browser_env["ABXPKG_LIB_DIR"] = str(tmp_path / "lib")
    source = tmp_path / "browser"
    httpserver.expect_request("/login").respond_with_data(
        '<html><title>Signed in</title><script>localStorage.setItem("persona-preference", "forest-green")</script>Signed in</html>',
        content_type="text/html",
        headers={"Set-Cookie": "persona_session=real-session; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax"},
    )

    def private_page(request):
        authenticated = request.cookies.get("persona_session") == "real-session"
        return Response(
            "<html><title>Private notebook</title><p>Authenticated persona notebook</p>"
            '<script>document.body.append(localStorage.getItem("persona-preference"))</script></html>'
            if authenticated
            else "<html>Please log in</html>",
            content_type="text/html",
        )

    httpserver.expect_request("/private").respond_with_handler(private_page)
    seeded = subprocess.run(
        [
            browser_env["NODE_BINARY"],
            "-e",
            """
const puppeteer = require(process.argv[1]);
(async () => {
    const browser = await puppeteer.launch({
        executablePath: process.argv[2], userDataDir: process.argv[3], headless: true,
        ignoreDefaultArgs: ['--use-mock-keychain', '--password-store=basic'],
        args: ['--no-sandbox', '--profile-directory=Profile 2'],
    });
    try {
        const page = await browser.newPage();
        await page.goto(process.argv[4]);
        console.log(await page.title());
        console.log(await page.evaluate(() => localStorage.getItem('persona-preference')));
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
""",
            str(tmp_path / "lib/pnpm/packages/chrome/node_modules/puppeteer"),
            browser_env["CHROME_BINARY"],
            str(source),
            httpserver.url_for("/login"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert seeded.returncode == 0, seeded.stderr
    assert "Signed in" in seeded.stdout
    assert "forest-green" in seeded.stdout
    command = get_plugin_catalog().find_command("browser-export-state")
    exported_auth = tmp_path / "exported-auth.json"
    exported = subprocess.run(
        [str(command.path), *command.args],
        input=json.dumps(
            {
                "config": {**browser_env, "CHROME_SANDBOX": False, "CHROME_CDP_URL": "http://127.0.0.1:1"},
                "user_data_dir": str(source),
                "profile_dir": "Profile 2",
                "browser_binary": browser_env["CHROME_BINARY"],
                "auth_output_file": str(exported_auth),
            },
        ),
        env={**os.environ, "CHROME_CDP_URL": "http://127.0.0.1:1"},
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert exported.returncode == 0, exported.stderr
    exported_cookies = json.loads(exported_auth.read_text())["cookies"]
    assert next(cookie for cookie in exported_cookies if cookie["name"] == "persona_session")["value"] == "real-session"
    preferences = source / "Profile 2" / "Preferences"
    original_preferences = preferences.read_bytes()

    imported = run_archivebox_cmd(
        [
            "persona",
            "create",
            "--import=chromium",
            "--source",
            str(source),
            "--browser-binary",
            browser_env["CHROME_BINARY"],
            "--profile=Profile 2",
            "session",
        ],
        cwd=initialized_archive,
        timeout=120,
        env={**browser_env, "CHROME_SANDBOX": "false", "CHROME_CDP_URL": "http://127.0.0.1:1"},
    )
    assert imported.returncode == 0, imported.stderr
    persona = initialized_archive / "personas" / "session"
    assert (persona / "chrome_profile" / "Default" / "Preferences").read_bytes() == original_preferences
    assert preferences.read_bytes() == original_preferences
    auth = json.loads((persona / "auth.json").read_text())
    cookie = next(cookie for cookie in auth["cookies"] if cookie["name"] == "persona_session")
    assert cookie["value"] == "real-session"
    assert cookie["httpOnly"] is True
    assert cookie["sameSite"] == "Lax"
    transferred = run_archivebox_cmd(
        ["persona", "create", f"--import={persona}", "portable"],
        cwd=initialized_archive,
        timeout=120,
    )
    assert transferred.returncode == 0, transferred.stderr
    portable = initialized_archive / "personas" / "portable"
    assert (portable / "auth.json").read_bytes() == (persona / "auth.json").read_bytes()
    assert (portable / "chrome_profile/Default/Preferences").read_bytes() == original_preferences
    before = {
        path.relative_to(persona): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (persona / "cookies.txt", persona / "auth.json", persona / "chrome_profile/Default/Preferences")
    }
    failed = run_archivebox_cmd(
        ["persona", "create", "--import=unsupported-browser", "--source", str(source), "--profile=Profile 2", "session"],
        cwd=initialized_archive,
        timeout=60,
    )
    assert failed.returncode == 1
    assert "browser executable not found" in " ".join(failed.stderr.split())
    assert all(hashlib.sha256((persona / relative).read_bytes()).hexdigest() == digest for relative, digest in before.items())

    archived = run_archivebox_cmd(
        ["add", "--persona=portable", "--plugins=dom", httpserver.url_for("/private")],
        cwd=initialized_archive,
        timeout=180,
        env={**browser_env, "CHROME_SANDBOX": "false"},
    )
    assert archived.returncode == 0, archived.stderr
    launch_commands = list((initialized_archive / "archive" / "users").glob("*/crawls/**/chrome/cmd.sh"))
    assert len(launch_commands) == 1
    launched_browser = Path(shlex.split(launch_commands[0].read_text().splitlines()[1])[0])
    # abxpkg's environment and provider projections can name the same binary.
    assert launched_browser.samefile(browser_env["CHROME_BINARY"])
    outputs = list((initialized_archive / "archive" / "users").glob("*/snapshots/**/dom/output.html"))
    assert len(outputs) == 1
    html = outputs[0].read_text()
    assert "Authenticated persona notebook" in html
    assert "forest-green" in html
    assert "Please log in" not in html
