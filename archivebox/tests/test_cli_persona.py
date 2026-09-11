#!/usr/bin/env python3
"""
Tests for archivebox persona command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_persona_help_runs_successfully(tmp_path):
    """The persona command should be registered and expose help."""

    result = run_archivebox_cmd(["persona", "--help"])

    assert result.returncode == 0
    assert "persona" in result.stdout.lower()
    assert "list" in result.stdout


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
    import subprocess

    from werkzeug.wrappers import Response
    from archivebox.tests.conftest import resolve_abxpkg_chrome_env

    browser_env = resolve_abxpkg_chrome_env(tmp_path / "lib")
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
        ["add", "--persona=session", "--plugins=dom", httpserver.url_for("/private")],
        cwd=initialized_archive,
        timeout=180,
        env={**browser_env, "CHROME_SANDBOX": "false"},
    )
    assert archived.returncode == 0, archived.stderr
    outputs = list((initialized_archive / "archive" / "users").glob("*/snapshots/**/dom/output.html"))
    assert len(outputs) == 1
    html = outputs[0].read_text()
    assert "Authenticated persona notebook" in html
    assert "forest-green" in html
    assert "Please log in" not in html
