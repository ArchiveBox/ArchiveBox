"""Exercise settings navigation and saving against the real admin/server forms."""

from playwright.sync_api import expect, sync_playwright

from .conftest import (
    cli_env,
    get_free_port,
    run_archivebox_cmd,
    run_python_cwd,
    start_archivebox_server,
    stop_archivebox_process,
)


def test_settings_keyboard_validation_and_persona_state(initialized_archive, browser_runtime):
    root = initialized_archive
    port = get_free_port()
    env = cli_env(
        BASE_URL=f"http://archivebox.localhost:{port}",
        BIND_ADDR=f"127.0.0.1:{port}",
        DJANGO_SUPERUSER_USERNAME="settings-navigation",
        DJANGO_SUPERUSER_PASSWORD="local-settings-navigation-password",
        DJANGO_SUPERUSER_EMAIL="settings@example.com",
    )
    for command in (["manage", "createsuperuser", "--noinput"], ["persona", "create", "Navigation Review"]):
        result = run_archivebox_cmd(command, cwd=root, env=env, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
    server = start_archivebox_server(root, port=port, env=env, log_name="server.log")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            base = f"http://admin.archivebox.localhost:{port}"
            page.goto(base + "/admin/login/")
            page.get_by_label("Username:", exact=True).fill(env["DJANGO_SUPERUSER_USERNAME"])
            page.get_by_label("Password:", exact=True).fill(env["DJANGO_SUPERUSER_PASSWORD"])
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page.locator(".navbar-username")).to_have_text(env["DJANGO_SUPERUSER_USERNAME"])
            page.goto(base + "/admin/personas/persona/")
            page.get_by_role("link", name="Navigation Review", exact=True).click()
            expect(page.locator("#plugin-settings")).to_be_visible()
            page.locator("#plugin-settings").scroll_into_view_if_needed()
            posted_urls = []
            page.on("request", lambda request: posted_urls.append(request.url) if request.method == "POST" else None)

            search = page.get_by_role("searchbox", name="Search plugin settings")
            expect(search).to_be_visible()
            screenshot_tab = page.locator('[role="tab"][data-plugin="screenshot"]')
            search.fill("screenshot")
            search.press("Enter")
            expect(screenshot_tab).to_be_focused()
            assert posted_urls == [], "Searching settings must not submit the Persona form"
            search.fill("")
            screenshot_tab.click()
            screenshot_tab.press("ArrowDown")
            pdf_tab = page.locator('[role="tab"][data-plugin="pdf"]')
            expect(pdf_tab).to_be_focused()
            expect(pdf_tab).to_have_attribute("aria-selected", "true")
            pdf_tab.press("Home")
            tabs = page.get_by_role("tab")
            expect(tabs.first).to_be_focused()
            tabs.first.press("ArrowUp")
            expect(tabs.last).to_be_focused()
            tabs.last.press("Home")
            tabs.first.press("End")
            expect(tabs.last).to_be_focused()

            sidebar_toggle = page.locator('.plugin-sidebar-toggle[data-plugin="screenshot"]')
            expect(sidebar_toggle).to_have_attribute("role", "switch")
            assert sidebar_toggle.get_attribute("name") is None, "The sidebar proxy must not duplicate submitted config"
            canonical_toggle = page.locator('[name="plugin_config__screenshot__SCREENSHOT_ENABLED"][type="checkbox"]')
            sidebar_toggle.uncheck()
            expect(canonical_toggle).not_to_be_checked()
            expect(tabs.last).to_have_attribute("aria-selected", "true")
            screenshot_tab.click()
            screenshot_tab.press("Tab")
            expect(sidebar_toggle).to_be_focused()
            sidebar_toggle.press("Tab")
            expect(page.locator('.plugin-card[data-plugin-name="screenshot"]')).to_be_focused()
            canonical_toggle.check()
            expect(sidebar_toggle).to_be_checked()
            canonical_toggle.uncheck()
            expect(sidebar_toggle).not_to_be_checked()

            timeout = page.locator('[name="plugin_config__screenshot__SCREENSHOT_TIMEOUT"]')
            timeout_slider = page.locator('.plugin-card[data-plugin-name="screenshot"] .config-timeout-slider')
            timeout_slider.fill("45")
            expect(timeout).to_have_value("45")
            expected_large_timeout = int(timeout_slider.get_attribute("max")) + 137
            timeout_field = page.locator(".plugin-config-field").filter(has=timeout)
            timeout_field.locator(".config-quantity-unit").select_option("s")
            timeout_field.locator(".config-quantity-value").fill(str(expected_large_timeout))
            expect(timeout).to_have_value(str(expected_large_timeout))
            expect(timeout_slider).to_have_value(str(expected_large_timeout))
            assert int(timeout_slider.get_attribute("max")) >= expected_large_timeout
            assert timeout.evaluate("input => input.validity.valid"), "The visual slider range must not restrict schema-valid values"
            screenshot_size = page.locator('[name="plugin_config__screenshot__SCREENSHOT_RESOLUTION"]')
            screenshot_size.fill("390,844")
            pdf_tab.click()
            pdf_size = page.locator('[name="plugin_config__pdf__PDF_RESOLUTION"]')
            pdf_size.fill("768,1024")
            page.locator('[role="tab"][data-plugin="chrome_screencast"]').click()
            scale = page.locator('[name="plugin_config__chrome_screencast__CHROME_SCREENCAST_SCALE"]')
            scale.fill("0.25")
            assert scale.evaluate("input => input.validity.valid"), "The schema allows non-tenth scale values"
            for plugin, key, unit, amount, raw in (
                ("infiniscroll", "INFINISCROLL_SCROLL_DELAY", "s", "2", "2000"),
                ("chrome", "CHROME_DELAY_AFTER_LOAD", "s", "0.25", "0.25"),
                ("tlsnotary", "TLSNOTARY_MAX_RECV_BYTES", "KiB", "128", "131072"),
            ):
                page.locator(f'[role="tab"][data-plugin="{plugin}"]').click()
                canonical = page.locator(f'[name="plugin_config__{plugin}__{key}"]')
                quantity = page.locator(".config-quantity").filter(has=canonical)
                quantity.locator(".config-quantity-unit").select_option(unit)
                quantity.locator(".config-quantity-value").fill(amount)
                expect(canonical).to_have_value(raw)
                assert quantity.locator(".config-quantity-value").evaluate("input => input.validity.valid")
            received_bytes = page.locator('[name="plugin_config__tlsnotary__TLSNOTARY_MAX_RECV_BYTES"]')
            received_amount = page.locator(".config-quantity").filter(has=received_bytes).locator(".config-quantity-value")
            received_amount.fill("257")
            assert not received_amount.evaluate("input => input.validity.valid"), "The schema maximum is 256 KiB"
            received_amount.fill("192")
            expect(received_bytes).to_have_value("196608")
            save = page.locator('button[name="_continue"]')
            save.click()
            expect(page.locator(".success")).to_be_visible()
            assert posted_urls
            page.locator('[role="tab"][data-plugin="chrome_screencast"]').click()
            expect(scale).to_have_value("0.25")
            screenshot_tab.click()
            expect(timeout).to_have_value(str(expected_large_timeout))
            expect(timeout_slider).to_have_value(str(expected_large_timeout))

            page.goto(base + "/add/")
            persona = page.locator('select[name="persona"]')
            persona.select_option(label="Default")
            screenshot_tab.click()
            capture_toggle = page.locator('.plugin-card[data-plugin-name="screenshot"] .plugin-section-toggle')
            expect(capture_toggle).to_be_checked()
            expect(sidebar_toggle).to_be_checked()
            pdf_tab.click()
            sidebar_toggle.uncheck()
            expect(capture_toggle).not_to_be_checked()
            expect(pdf_tab).to_have_attribute("aria-selected", "true")
            sidebar_toggle.check()
            expect(capture_toggle).to_be_checked()
            expect(pdf_tab).to_have_attribute("aria-selected", "true")
            persona.select_option(label="Navigation Review")
            expect(capture_toggle).not_to_be_checked()
            expect(sidebar_toggle).not_to_be_checked()
            expect(screenshot_size).to_have_value("390,844")
            expect(timeout).to_have_value(str(expected_large_timeout))
            persona.select_option(label="Default")
            expect(capture_toggle).to_be_checked()
            expect(sidebar_toggle).to_be_checked()
            for key, unit, amount, raw in (
                ("crawl_max_size", "GiB", "1.5", "1610612736"),
                ("crawl_timeout", "min", "1.5", "90"),
            ):
                canonical = page.locator(f'[name="{key}"]')
                quantity = page.locator(".config-quantity").filter(has=canonical)
                quantity.locator(".config-quantity-unit").select_option(unit)
                quantity.locator(".config-quantity-value").fill(amount)
                expect(canonical).to_have_value(raw)
                assert quantity.locator(".config-quantity-value").evaluate("input => input.validity.valid")
            page.locator('[name="url"]').fill("https://example.com/settings-validation")
            save = page.locator("#submit")
            # Both invalid fields participate in native validation even after their panels are hidden.
            screenshot_tab.click()
            screenshot_size.fill("invalid screenshot size")
            pdf_tab.click()
            pdf_size.fill("invalid PDF size")
            page.locator('[role="tab"][data-plugin="puppeteer"]').click()
            posts_before_invalid_save = len(posted_urls)
            save.click()
            expect(screenshot_size).to_be_visible()
            expect(screenshot_size).to_be_focused()
            expect(pdf_size).not_to_be_visible()
            assert len(posted_urls) == posts_before_invalid_save
            screenshot_size.fill("390,844")
            save.click()
            expect(pdf_size).to_be_visible()
            expect(pdf_size).to_be_focused()
            assert len(posted_urls) == posts_before_invalid_save
            pdf_size.fill("768,1024")
            browser.close()

        stdout, stderr, returncode = run_python_cwd(
            "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings'); "
            "import django; django.setup(); from archivebox.personas.models import Persona; "
            "config = Persona.objects.get(name='Navigation Review').config; "
            "assert config['CHROME_SCREENCAST_SCALE'] == 0.25, config; "
            "assert config['CHROME_DELAY_AFTER_LOAD'] == 0.25, config; "
            "assert config['TLSNOTARY_MAX_RECV_BYTES'] == 196608, config; "
            f"assert config['SCREENSHOT_TIMEOUT'] == {expected_large_timeout}, config; "
            "assert config['SCREENSHOT_ENABLED'] is False, config; "
            "assert config['SCREENSHOT_RESOLUTION'] == '390,844', config; "
            "assert config['PDF_RESOLUTION'] == '768,1024', config; print('saved values verified')",
            cwd=root,
        )
        assert returncode == 0, stdout + stderr
        assert "saved values verified" in stdout
    finally:
        stop_archivebox_process(server)
