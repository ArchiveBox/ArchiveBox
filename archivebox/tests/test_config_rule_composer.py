"""Exercise URL rule generation and preview through the authenticated server."""

import json
import os
import re
import sqlite3
from pathlib import Path

import requests
from playwright.sync_api import expect, sync_playwright

from .conftest import (
    cli_env,
    create_admin_and_token,
    get_free_port,
    run_archivebox_cmd,
    run_python_cwd,
    start_archivebox_server,
    stop_archivebox_process,
)
from .test_ui_add_view_runtime import _login_to_add_view


def test_url_rule_composer_uses_crawl_filter_semantics(initialized_archive):
    root = initialized_archive
    create_admin_and_token(root)
    port = get_free_port()
    server = start_archivebox_server(root, env=cli_env(port=port, server=True), port=port, log_name="rules-server.log")
    try:
        session, _page, csrf = _login_to_add_view(port)
        host = f"admin.archivebox.localhost:{port}"
        endpoint = f"http://127.0.0.1:{port}/admin/settings/url-rules/preview/"
        headers = {"Host": host, "Referer": f"http://{host}/add/", "X-CSRFToken": csrf}

        def post(**payload):
            response = session.post(endpoint, headers=headers, json=payload, timeout=10)
            assert response.status_code == 200, response.text
            return response.json()

        for mode, accepted, rejected in (
            (
                "domain",
                ["https://example.com/", "HTTP://EXAMPLE.COM:8080/a"],
                ["https://sub.example.com/", "https://example.com.evil/", "https://evil/?example.com"],
            ),
            ("subdomains", ["https://example.com/", "https://a.b.example.com/x"], ["https://notexample.com/", "https://example.com.evil/"]),
            (
                "path",
                ["https://example.com/Docs", "https://example.com/Docs?x=1"],
                ["https://example.com/docs", "https://example.com/Docs/a", "https://example.com/DocsExtra"],
            ),
            (
                "descendants",
                ["https://example.com/Docs", "https://example.com/Docs/a"],
                ["https://example.com/docs", "https://example.com/DocsExtra"],
            ),
        ):
            generated = post(entries="https://example.com/Docs", mode=mode)["generated"]
            result = post(allowlist=generated, denylist="", urls="\n".join(accepted + rejected))
            assert result["errors"] == []
            assert [row["allowed"] for row in result["results"]] == [True] * len(accepted) + [False] * len(rejected), result

        # Existing bare-domain rules include subdomains; deny wins, and raw regex is case sensitive.
        result = post(
            allowlist="example.com",
            denylist="/Blocked",
            urls="https://a.example.com/ok\nhttps://example.com/Blocked\nhttps://example.com/blocked\nhttps://elsewhere.test/",
        )
        assert [row["allowed"] for row in result["results"]] == [True, False, True, False]
        assert result["results"][1]["reason"] == "denylist"
        assert result["results"][1]["deny_matches"] == ["/Blocked"]
        assert post(allowlist="", denylist="", urls="https://elsewhere.test/")["results"][0]["allowed"] is True
        assert post(allowlist="[", denylist="", urls="https://example.com/")["errors"][0]["field"] == "allowlist"
        assert post(allowlist="*.example.com", denylist="", urls="https://a.example.com/")["errors"] == []
        assert post(entries="example.com\nexample.com\nexample.org", mode="domain")["generated"].count("\n") == 1
        root_rule = post(entries="https://example.com/", mode="path")["generated"]
        assert [
            row["allowed"]
            for row in post(allowlist=root_rule, urls="https://example.com\nhttps://example.com/?x=1\nhttps://example.com/a")["results"]
        ] == [True, True, False]
        port_rule = post(entries="https://example.com:8443/a+b", mode="path")["generated"]
        assert [
            row["allowed"]
            for row in post(allowlist=port_rule, urls="https://example.com:8443/a+b\nhttps://example.com/a+b\nhttps://example.com:8443/ab")[
                "results"
            ]
        ] == [True, False, False]
        invalid = session.post(endpoint, headers=headers, json={"entries": "javascript:alert(1)", "mode": "domain"}, timeout=10)
        assert invalid.status_code == 400
        assert session.get(endpoint, headers={"Host": host}, timeout=10).status_code == 405
        assert session.post(endpoint, headers={"Host": host}, json={"urls": "https://example.com/"}, timeout=10).status_code == 403

        anonymous = requests.Session()
        login = anonymous.get(f"http://127.0.0.1:{port}/admin/login/", headers={"Host": host}, timeout=10)
        anonymous_csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login.text).group(1)
        forbidden = anonymous.post(
            endpoint,
            headers={**headers, "X-CSRFToken": anonymous_csrf},
            json={"urls": "https://example.com/"},
            timeout=10,
        )
        assert forbidden.status_code == 403
        created = run_archivebox_cmd(
            [
                "manage",
                "shell",
                "-c",
                "from django.contrib.auth import get_user_model; get_user_model().objects.create_user(username='rules-staff', password='rules-password', is_staff=True)",
            ],
            cwd=root,
            timeout=60,
        )
        assert created.returncode == 0, created.stdout + created.stderr
        logged_in = anonymous.post(
            f"http://127.0.0.1:{port}/admin/login/",
            headers={"Host": host, "Referer": f"http://{host}/admin/login/"},
            data={"csrfmiddlewaretoken": anonymous_csrf, "username": "rules-staff", "password": "rules-password", "next": "/admin/"},
            allow_redirects=False,
            timeout=10,
        )
        assert logged_in.status_code == 302
        staff_page = anonymous.get(f"http://127.0.0.1:{port}/add/", headers={"Host": host}, timeout=10)
        staff_csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', staff_page.text).group(1)
        forbidden = anonymous.post(
            endpoint,
            headers={**headers, "X-CSRFToken": staff_csrf},
            json={"urls": "https://example.com/"},
            timeout=10,
        )
        assert forbidden.status_code == 403
    finally:
        stop_archivebox_process(server)


def test_add_rule_composer_and_concurrency_save_existing_values(initialized_archive, browser_runtime):
    root = initialized_archive
    create_admin_and_token(root)
    port = get_free_port()
    server = start_archivebox_server(root, env=cli_env(port=port, server=True), port=port, log_name="rules-browser.log")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            base = f"http://admin.archivebox.localhost:{port}"
            page.goto(base + "/admin/login/")
            page.get_by_label("Username:", exact=True).fill("apitestadmin")
            page.get_by_label("Password:", exact=True).fill("testpass123")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.goto(base + "/add/")
            page.locator('[name="url"]').fill("https://example.com/docs/article")
            patterns = page.locator("details.url-filter-patterns")
            if patterns.count():
                patterns.locator("summary").click()
            allow = page.locator(".config-url-rules").filter(has=page.locator('[name="url_filters_allowlist"]'))
            deny = page.locator(".config-url-rules").filter(has=page.locator('[name="url_filters_denylist"]'))
            allow.locator("[data-rule-entries]").fill("example.com")
            allow.locator("[data-rule-mode]").select_option("subdomains")
            allow.get_by_role("button", name="Replace rules", exact=True).click()
            expect(allow.locator(".config-rule-raw")).to_have_value(re.compile(r"^\(\?i:\^https\?://"))
            initial = allow.locator(".config-rule-raw").input_value()
            allow.locator("[data-rule-entries]").fill("https://example.org/docs")
            allow.locator("[data-rule-mode]").select_option("descendants")
            allow.get_by_role("button", name="Add rules", exact=True).click()
            expect(allow.locator(".config-rule-raw")).to_have_value(re.compile(r"example\\\.org"))
            allowed_rules = allow.locator(".config-rule-raw").input_value()
            assert allowed_rules.startswith(initial + "\n")
            assert len(allowed_rules.splitlines()) == 2
            deny.locator(".config-rule-raw").fill("/blocked")
            allow.locator("summary").click()
            allow.locator("[data-rule-urls]").fill("https://a.example.com/ok\nhttps://example.com/blocked\nhttps://elsewhere.test/")
            allow.get_by_role("button", name="Test URLs", exact=True).click()
            expect(allow.locator(".config-rule-results strong")).to_have_text(["Included", "Excluded", "Excluded"])

            concurrency = page.locator(".config-concurrency")
            concurrency.get_by_role("button", name="Fixed limit", exact=True).click()
            limit = page.locator('[name="crawl_max_concurrent_snapshots"]')
            limit.fill("48")
            expect(concurrency.locator("[data-concurrency-slider]")).to_have_attribute("max", "48")
            concurrency.get_by_role("button", name="Automatic", exact=True).click()
            expect(limit).to_have_value("0")
            concurrency.get_by_role("button", name="Fixed limit", exact=True).click()
            expect(limit).to_have_value("48")
            assert allow.locator("[data-rule-entries]").bounding_box()["height"] < 120
            assert allow.locator(".config-rule-raw").bounding_box()["height"] < 160
            assert concurrency.bounding_box()["x"] + concurrency.bounding_box()["width"] <= page.viewport_size["width"]
            if artifact_dir := os.environ.get("ABX_SETTINGS_ARTIFACT_DIR"):
                artifacts = Path(artifact_dir)
                artifacts.mkdir(parents=True, exist_ok=True)
                page.get_by_role("heading", name="Create a new Crawl", exact=True).click()
                page.screenshot(path=str(artifacts / "add.png"), full_page=True)
            page.locator(".advanced-section > summary").click()
            page.locator('[name="start_paused"]').check()
            page.locator('#add-form button[type="submit"]').click()
            page.wait_for_url(re.compile(r"/admin/crawls/crawl/"))
            browser.close()
        saved = run_archivebox_cmd(
            [
                "manage",
                "shell",
                "-c",
                "import json; from archivebox.crawls.models import Crawl; c=Crawl.objects.latest('created_at'); print(json.dumps({'config': c.config, 'status': c.status}))",
            ],
            cwd=root,
            timeout=60,
        )
        assert saved.returncode == 0, saved.stdout + saved.stderr
        result = json.loads(saved.stdout.strip().splitlines()[-1])
        assert result["config"]["URL_ALLOWLIST"] == allowed_rules
        assert result["config"]["URL_DENYLIST"] == "/blocked"
        assert result["config"]["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 48
        assert result["status"] == "paused"
    finally:
        stop_archivebox_process(server)


def test_machine_plugin_chips_preserve_and_save_csv(initialized_archive, browser_runtime):
    root = initialized_archive
    create_admin_and_token(root)
    stdout, stderr, code = run_python_cwd(
        "import django; django.setup(); from archivebox.machine.models import Machine; "
        "machine=Machine.current(); machine.config.update(PLUGINS='wget, pdf', CRAWL_DISCOVERY_PLUGINS='parse_html_urls, parse_dom_outlinks'); "
        "machine.save(update_fields=['config']); print(machine.pk)",
        cwd=root,
    )
    assert code == 0, stderr
    machine_id = stdout.strip().splitlines()[-1]

    def stored():
        with sqlite3.connect(f"file:{root / 'index.sqlite3'}?mode=ro", uri=True) as connection:
            return json.loads(connection.execute("SELECT config FROM machine_machine WHERE id = ?", (machine_id,)).fetchone()[0])

    before = stored()
    port = get_free_port()
    server = start_archivebox_server(
        root,
        env=cli_env(BASE_URL=f"http://archivebox.localhost:{port}", BIND_ADDR=f"127.0.0.1:{port}"),
        port=port,
        log_name="plugin-chips-browser.log",
    )
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            context = browser.new_context(viewport={"width": 1440, "height": 1100}, permissions=["clipboard-read", "clipboard-write"])
            page = context.new_page()
            base = f"http://admin.archivebox.localhost:{port}"
            page.goto(base + "/admin/login/")
            page.get_by_label("Username:", exact=True).fill("apitestadmin")
            page.get_by_label("Password:", exact=True).fill("testpass123")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.goto(base + "/admin/settings/")
            plugins = page.locator(".config-plugin-list").filter(has=page.locator('[data-config-key="PLUGINS"][name]'))
            discovery = page.locator(".config-plugin-list").filter(has=page.locator('[data-config-key="CRAWL_DISCOVERY_PLUGINS"][name]'))
            expect(plugins.locator(".plugin-config-input")).to_have_value("wget, pdf")
            expect(plugins.locator(".config-plugin-chip")).to_have_count(2)
            expect(discovery.locator(".plugin-config-input")).to_have_value("parse_html_urls, parse_dom_outlinks")
            page.get_by_role("button", name="Save settings", exact=True).click()
            expect(page.locator(".success")).to_be_visible()
            assert stored() == before, "Rendering chips and saving unchanged must preserve exact CSV spacing"

            page.locator('[role="tab"][data-plugin="archiving_config"]').click()
            plugins.locator('.config-plugin-chip[title="pdf"] button').click()
            entry = plugins.locator(".config-plugin-autocomplete")
            expect(plugins.locator('datalist option[value="title"]')).to_have_count(1)
            assert entry.get_attribute("list") == plugins.locator("datalist").get_attribute("id")
            entry.fill("title")
            entry.press("Enter")
            expect(plugins.locator(".plugin-config-input")).to_have_value("wget,title")
            page.evaluate("navigator.clipboard.writeText('pdf,screenshot')")
            entry.focus()
            entry.press("ControlOrMeta+V")
            expect(plugins.locator(".plugin-config-input")).to_have_value("wget,title,pdf,screenshot")
            search = page.get_by_role("searchbox", name="Search plugin settings")
            search.fill("CRAWL_DISCOVERY_PLUGINS")
            discovery.locator('.config-plugin-chip[title="parse_dom_outlinks"] button').click()
            discovery.locator(".config-plugin-autocomplete").fill("parse_txt_urls")
            discovery.locator(".config-plugin-autocomplete").press("Enter")
            expect(discovery.locator(".plugin-config-input")).to_have_value("parse_html_urls,parse_txt_urls")
            page.get_by_role("button", name="Save settings", exact=True).click()
            expect(page.locator(".success")).to_be_visible()
            assert stored() == {
                **before,
                "PLUGINS": "wget,title,pdf,screenshot",
                "CRAWL_DISCOVERY_PLUGINS": "parse_html_urls,parse_txt_urls",
            }

            page.locator('[role="tab"][data-plugin="archiving_config"]').click()
            search.fill("CRAWL_DISCOVERY_PLUGINS")
            expect(discovery.locator(".config-plugin-autocomplete")).to_be_visible()
            search.fill("")
            if artifact_dir := os.environ.get("ABX_SETTINGS_ARTIFACT_DIR"):
                artifacts = Path(artifact_dir)
                artifacts.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(artifacts / "system-plugins.png"), full_page=True)
            for _ in range(4):
                plugins.locator(".config-plugin-chip button").first.click()
            expect(plugins.locator(".plugin-config-input")).to_have_value("")
            page.get_by_role("button", name="Save settings", exact=True).click()
            expect(page.locator(".success")).to_be_visible()
            assert stored().get("PLUGINS", "") == ""
            assert stored()["CRAWL_DISCOVERY_PLUGINS"] == "parse_html_urls,parse_txt_urls"
            browser.close()
    finally:
        stop_archivebox_process(server)
