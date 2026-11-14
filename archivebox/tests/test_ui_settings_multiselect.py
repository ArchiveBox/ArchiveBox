import json
import sqlite3

from playwright.sync_api import expect, sync_playwright

from archivebox.tests.conftest import cli_env, get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process


def test_plugin_array_enum_round_trips_through_settings(initialized_archive, browser_runtime):
    root = initialized_archive
    port = get_free_port()
    env = cli_env(
        BASE_URL=f"http://archivebox.localhost:{port}",
        BIND_ADDR=f"127.0.0.1:{port}",
        DJANGO_SUPERUSER_USERNAME="formats-review",
        DJANGO_SUPERUSER_PASSWORD="formats-review-local-password",
        DJANGO_SUPERUSER_EMAIL="formats@example.com",
    )
    result = run_archivebox_cmd(["manage", "createsuperuser", "--noinput"], cwd=root, env=env)
    assert result.returncode == 0, result.stderr
    server = start_archivebox_server(root, port=port, env=env, log_name="formats-server.log")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page()
            base = f"http://admin.archivebox.localhost:{port}"
            page.goto(base + "/admin/login/")
            page.get_by_label("Username:", exact=True).fill(env["DJANGO_SUPERUSER_USERNAME"])
            page.get_by_label("Password:", exact=True).fill(env["DJANGO_SUPERUSER_PASSWORD"])
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page.locator(".navbar-username")).to_have_text(env["DJANGO_SUPERUSER_USERNAME"])
            page.goto(base + "/admin/settings/")
            search = page.get_by_role("searchbox", name="Search plugin settings")
            search.fill("GOOGLEDOCS_FORMATS")
            formats = page.locator('select[name="plugin_config__googledocs__GOOGLEDOCS_FORMATS"]')
            expect(formats).to_have_values(["docx", "xlsx", "pptx", "csv", "pdf", "svg"])
            for selection in (["pdf", "md"], [], ["docx", "xlsx", "pptx", "csv", "pdf", "svg"]):
                formats.select_option(selection)
                page.get_by_role("button", name="Save settings", exact=True).click()
                expect(page.locator(".success")).to_be_visible()
                search.fill("GOOGLEDOCS_FORMATS")
                expect(formats).to_have_values(selection)
                with sqlite3.connect(f"file:{root / 'index.sqlite3'}?mode=ro", uri=True) as connection:
                    configs = [json.loads(row[0]) for row in connection.execute("SELECT config FROM machine_machine")]
                matching = [config for config in configs if "GOOGLEDOCS_FORMATS" in config]
                if len(selection) == 6:
                    assert not matching, configs
                else:
                    assert len(matching) == 1, configs
                    assert matching[0]["GOOGLEDOCS_FORMATS"] == selection
                page.get_by_role("button", name="Save settings", exact=True).click()
                expect(page.locator(".success")).to_be_visible()
                search.fill("GOOGLEDOCS_FORMATS")
                expect(formats).to_have_values(selection)
            browser.close()
    finally:
        stop_archivebox_process(server)
