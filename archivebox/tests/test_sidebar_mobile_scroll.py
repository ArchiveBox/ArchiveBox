from urllib.parse import urlsplit

import pytest

from archivebox.core.models import Folder, Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_mobile_sidebar_scroll_and_paginate(live_server, admin_user, browser_runtime):
    from playwright.sync_api import expect, sync_playwright

    base = f"http://archivebox.localhost:{urlsplit(live_server.url).port}"
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": base, "PUBLIC_INDEX": True}
    machine.save(update_fields=["config"])
    folders = Folder.objects.bulk_create([Folder(name=f"Demo folder {i:03}", position=i) for i in range(106)])
    tags = Tag.objects.bulk_create([Tag(name=f"Demo tag {i:03}") for i in range(106)])
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://demo000.example/")
    for i, (folder, tag) in enumerate(zip(folders, tags)):
        s = Snapshot.objects.create(
            crawl=crawl,
            folder=folder,
            url=f"https://demo{i:03}.example/",
            title=f"Demo saved page {i:03}",
            config={"PERMISSIONS": "public"},
        )
        s.tags.add(tag)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        admin = base.replace("//archivebox", "//admin.archivebox")
        page.goto(admin + "/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        nav = page.locator("#folder-sidebar")
        expect(nav.locator(".folder-mobile-toggle")).to_have_attribute("aria-expanded", "false")
        for mode, menu_name in (("tags", "Tags"), ("domains", "Domains"), ("folders", "All folders")):
            toggle = nav.locator(".folder-mobile-toggle")
            if toggle.get_attribute("aria-expanded") == "true":
                toggle.click()
            expect(toggle).to_have_attribute("aria-expanded", "false")
            nav.get_by_role("button", name="Choose sidebar view").click()
            option = nav.get_by_role("menuitem", name=menu_name, exact=True)
            if mode == "domains":
                option.press("Enter")
            else:
                option.tap()
            expect(nav).to_have_attribute("data-mode", mode)
            expect(toggle).to_have_attribute("aria-expanded", "true", timeout=2000)
            expect(nav.locator(".folder-tree")).to_be_visible()
            expect(nav.locator(".folder-actions")).to_be_visible()
        page.reload()
        expect(nav.locator(".folder-mobile-toggle")).to_have_attribute("aria-expanded", "false")
        for width, height in [(390, 844), (320, 568), (430, 932), (640, 360)]:
            page.set_viewport_size({"width": width, "height": height})
            for mode in ("folders", "tags", "domains"):
                response = page.goto(admin + f"/admin/core/snapshot/?sidebar={mode}", wait_until="domcontentloaded")
                assert response.status == 200
                nav = page.locator("#folder-sidebar")
                tree = nav.locator(".folder-tree")
                toggle = nav.locator(".folder-mobile-toggle")
                if toggle.get_attribute("aria-expanded") == "false":
                    toggle.click()
                expect(toggle).to_have_attribute("aria-expanded", "true")
                row_sel = ".folder-row" if mode == "folders" else ".library-entry"
                rows = tree.locator(row_sel)
                expect(rows).to_have_count(100)
                box = nav.bounding_box()
                tree_metrics = tree.evaluate("el => [el.clientHeight, el.scrollHeight]")
                assert box["height"] <= max(124, height * 0.25) + 1, box
                assert tree_metrics[0] >= 30 and tree_metrics[1] > tree_metrics[0]
                footer = nav.locator(".folder-actions")
                expect(footer.locator(".library-import-toggle")).to_be_visible()
                expect(footer.locator(".library-export-toggle")).to_be_visible()
                actions_before = footer.bounding_box()
                assert tree.bounding_box()["y"] + tree_metrics[0] <= actions_before["y"] + 1
                assert actions_before["y"] + actions_before["height"] <= box["y"] + box["height"] + 1
                tree.hover(position={"x": 14, "y": min(12, tree_metrics[0] - 1)})
                before = page.evaluate("scrollY")
                with page.expect_response(lambda r: "/sidebar/" in r.url and "cursor=" in r.url, timeout=5000) as loaded:
                    page.mouse.wheel(0, tree_metrics[1])
                assert loaded.value.ok
                expect(rows).to_have_count(107 if mode == "folders" else 106)
                assert tree.evaluate("el => el.scrollTop") > 0 and page.evaluate("scrollY") == before
                expect(tree.locator(".library-load-more")).to_be_hidden()
                assert footer.bounding_box() == actions_before
                if (width, height) == (390, 844):
                    for kind in ("import", "export"):
                        control = footer.locator(f".library-{kind}-toggle")
                        menu = page.locator("#" + control.get_attribute("popovertarget"))
                        control.click()
                        expect(menu).to_be_visible()
                        items = menu.get_by_role("menuitem")
                        assert items.count() >= 5
                        for item in items.all():
                            expect(item).to_be_in_viewport(ratio=0.95)
                            assert item.get_attribute("href")
                        page.keyboard.press("Escape")
                        expect(menu).to_be_hidden()
        browser.close()
