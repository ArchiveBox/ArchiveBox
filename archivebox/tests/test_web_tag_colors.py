from urllib.parse import urlsplit

import pytest


@pytest.mark.django_db(transaction=True)
def test_same_color_for_web_tag_badges(browser_runtime, live_server, admin_user, snapshot):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Tag
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    origin = f"http://archivebox.localhost:{port}"
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": origin, "SERVER_SECURITY_MODE": "safe-onedomain-nojsreplay"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    name = "Édition😺"
    tag = Tag.objects.create(name=name)
    snapshot.tags.set([tag])

    def badge_colors(pill):
        expect(pill).to_be_visible()
        return pill.evaluate("el => {const s = getComputedStyle(el); return [s.color, s.backgroundColor, s.borderTopColor]}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{origin}/admin/login/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()

            page.goto(f"{origin}/admin/core/snapshot/")
            pill = page.locator("#result_list .tag-pill").filter(has_text=name)
            palette = badge_colors(pill)
            link = pill.get_by_role("link", name=name)
            assert link.get_attribute("href").endswith(f"tags__id__exact={tag.pk}")
            assert link.evaluate("el => getComputedStyle(el).color") == palette[0]
            assert link.evaluate("el => getComputedStyle(el).textDecorationLine") == "none"
            link.hover()
            assert link.evaluate("el => getComputedStyle(el).textDecorationLine") == "none"
            editor = page.locator("#result_list .tag-editor-inline").first
            inline_input = editor.locator(".tag-inline-input-sm")
            inline_input.focus()
            pill.locator(".tag-remove-btn").click()
            expect(pill).to_have_count(0)
            inline_input.fill(name)
            inline_input.press("Enter")
            assert badge_colors(pill) == palette
            inline_input.blur()
            expect(pill.get_by_role("link", name=name)).to_have_attribute("href", f"/admin/core/snapshot/?tags__id__exact={tag.pk}")
            with page.expect_request(f"{origin}/admin/core/snapshot/?tags__id__exact={tag.pk}", timeout=4000):
                pill.get_by_role("link", name=name).click()

            page.goto(f"{origin}{snapshot.get_absolute_url()}/index.html")
            assert badge_colors(page.locator(".header-tags > summary .tag-pill").filter(has_text=name)) == palette
            public_page = browser.new_page(viewport={"width": 1440, "height": 900})
            public_page.goto(f"{origin}/public/")
            assert badge_colors(public_page.locator(".snapshot-tag").filter(has_text=name)) == palette
            public_page.close()

            page.goto(f"{origin}/add/")
            field = page.locator(".tag-inline-input")
            field.fill(f"  {name.upper()}  ")
            field.press("Enter")
            chip = page.locator(".tag-pills .tag-pill").filter(has_text=name.upper())
            assert badge_colors(chip) == palette
            chip.locator(".tag-remove-btn").click()
            expect(chip).to_have_count(0)
        finally:
            browser.close()
