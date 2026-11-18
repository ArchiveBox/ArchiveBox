"""Exercise schedule shortcuts through a real importer form and browser."""

import pytest
from playwright.sync_api import expect, sync_playwright

from archivebox.importers.models import ImporterSource
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_schedule_shortcuts_overwrite_without_submitting(live_server, admin_user, browser_runtime):
    machine = Machine.current()
    machine.config.update(BASE_URL=live_server.url, SERVER_SECURITY_MODE="safe-onedomain-nojsreplay")
    machine.save(update_fields=["config"])
    url = f"{live_server.url}/admin/importers/new/importer_rss/feed/"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"{live_server.url}/admin/login/?next=/admin/importers/new/importer_rss/feed/")
        page.get_by_label("Username:", exact=True).fill(admin_user.username)
        page.get_by_label("Password:", exact=True).fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.get_by_text("Advanced options", exact=True).click()
        field = page.get_by_label("Schedule:", exact=True)
        field.fill("0 */6 * * *")
        daily = page.get_by_role("button", name="Set schedule to daily", exact=True)
        weekly = page.get_by_role("button", name="Set schedule to weekly", exact=True)
        daily.click()
        expect(field).to_have_value("daily")
        expect(field).to_be_focused()
        weekly.press("Enter")
        expect(field).to_have_value("weekly")
        expect(field).to_be_focused()
        daily.click()
        expect(field).to_have_value("daily")
        field.fill("0 3 * * 1")
        expect(field).to_have_value("0 3 * * 1")
        assert page.url == url
        geometry = page.locator(".schedule-presets").evaluate("""element => {
            const input = element.querySelector('input').getBoundingClientRect();
            const buttons = element.querySelector('.schedule-presets-shortcuts').getBoundingClientRect();
            return {inputTop: input.top, inputRight: input.right, buttonsBottom: buttons.bottom,
                    buttonsRight: buttons.right, buttonsLeft: buttons.left, viewport: innerWidth};
        }""")
        assert geometry["buttonsBottom"] <= geometry["inputTop"]
        assert geometry["buttonsRight"] <= geometry["inputRight"]
        assert 0 <= geometry["buttonsLeft"] < geometry["buttonsRight"] <= geometry["viewport"]
        browser.close()
    assert not ImporterSource.objects.exists()
