"""Scroll the real shared settings sidebar with a mouse wheel."""

from urllib.parse import urlsplit

import pytest
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from archivebox.machine.models import Machine
from archivebox.personas.models import Persona


@pytest.mark.django_db(transaction=True)
def test_settings_sidebar_scrollbar_and_last_tab(live_server, admin_user, browser_runtime):
    machine = Machine.current()
    port = urlsplit(live_server.url).port
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    persona = Persona.objects.create(name="Sidebar wheel test")
    base = f"http://admin.archivebox.localhost:{port}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.goto(base + "/admin/login/")
        page.get_by_label("Username:", exact=True).fill(admin_user.username)
        page.get_by_label("Password:", exact=True).fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        for path in (
            reverse("admin:personas_persona_add"),
            reverse("admin:personas_persona_change", args=[persona.pk]),
            reverse("admin:machine_machine_change", args=[machine.pk]),
            "/add/",
        ):
            for width, height in ((1440, 500), (390, 680)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(base + path)
                rail = page.locator(".plugin-settings-tabs")
                expect(rail.get_by_role("tab").first).to_be_enabled()
                rail.scroll_into_view_if_needed()
                style = rail.evaluate("""node => ({
                    width: getComputedStyle(node, '::-webkit-scrollbar').width,
                    thumb: getComputedStyle(node, '::-webkit-scrollbar-thumb').backgroundColor,
                    standardWidth: getComputedStyle(node).scrollbarWidth,
                    overflows: node.scrollHeight > node.clientHeight,
                    gutter: node.offsetWidth - node.clientWidth,
                })""")
                assert style["overflows"], (path, width, style)
                assert style["width"] == "8px" and style["gutter"] >= 8, (path, width, style)
                assert style["standardWidth"] == "auto" and style["thumb"] != "rgba(0, 0, 0, 0)", (path, width, style)
                rail.hover()
                page.mouse.wheel(0, 10000)
                page.wait_for_function("""() => {
                    const rail = document.querySelector('.plugin-settings-tabs');
                    const bottom = rail.getBoundingClientRect().bottom;
                    const last = [...rail.querySelectorAll('[role="tab"]')].at(-1);
                    return rail.scrollTop > 0 && last.getBoundingClientRect().bottom <= bottom + 1;
                }""")
                last_tab = rail.get_by_role("tab").last
                last_tab.click()
                expect(last_tab).to_have_attribute("aria-selected", "true")
                active_id = last_tab.get_attribute("aria-controls")
                expect(page.locator(f'[id="{active_id}"]')).to_be_visible()
