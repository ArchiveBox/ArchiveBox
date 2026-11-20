import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from archivebox.core.models import Folder
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_snapshot_drag_dwell_reopens_hidden_folder_sidebar(live_server, admin_user, snapshot, browser_runtime):
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    parent = Folder.objects.create(name="Research")
    child = Folder.objects.create(name="Papers", parent=parent)
    original_folder = snapshot.folder_id
    origin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{origin}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        sidebar = page.locator(".folder-sidebar")
        hide = sidebar.get_by_role("button", name="Hide folders", exact=True)
        library = page.locator(".snapshot-library")
        row = page.locator('#result_list tbody tr[draggable="true"] .field-title_str')
        expect(row).to_have_count(1)
        parent_row = sidebar.locator(f'.folder-row[data-folder-id="{parent.pk}"]')
        child_row = sidebar.locator(f'.folder-row[data-folder-id="{child.pk}"]')
        parent_row.get_by_role("button", name="Collapse Research").click()
        expect(child_row).to_be_hidden()
        hide.click()
        expect(sidebar).to_be_hidden()
        posts = []
        page.on("request", lambda req: posts.append(urlsplit(req.url).path) if req.method == "POST" else None)

        # Native mouse gestures, including moving twice for Chromium dragover.
        def start_drag():
            point = row.bounding_box()
            x, y = point["x"] + 20, point["y"] + point["height"] / 2
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x - 24, y, steps=4)
            expect(page.locator("body")).to_have_class(re.compile(r"\bdragging-snapshots\b"))
            return y

        def move_to_edge(y):
            page.mouse.move(3, y)
            page.mouse.move(2, y)

        def cancel_drag():
            page.keyboard.press("Escape")
            page.mouse.up()
            expect(page.locator(".snapshot-drag-badge")).to_have_count(0)

        # A native link drag and an ordinary scroll don't count as Snapshot drags.
        brand = page.locator("#site-name .branding-label")
        brand.hover()
        page.mouse.down()
        move_to_edge(brand.bounding_box()["y"] + 8)
        page.mouse.wheel(0, 80)
        page.wait_for_timeout(1100)
        expect(sidebar).to_be_hidden()
        cancel_drag()

        page.mouse.move(2, 200)
        y = start_drag()
        move_to_edge(y)
        page.mouse.move(70, y)
        page.wait_for_timeout(1100)  # A canceled dwell must outlast the opening threshold.
        expect(sidebar).to_be_hidden()
        page.mouse.up()

        y = start_drag()
        move_to_edge(y)
        cancel_drag()
        page.wait_for_timeout(1100)
        expect(sidebar).to_be_hidden()

        y = start_drag()
        move_to_edge(y)
        page.mouse.up()
        expect(page.locator(".snapshot-drag-badge")).to_have_count(0)
        page.wait_for_timeout(1100)
        expect(sidebar).to_be_hidden()

        # Deterministically reproduce a list-panel replacement during a real drag.
        page.evaluate("window.beforeDragForm = document.querySelector('#changelist-form').cloneNode(true)")
        y = start_drag()
        move_to_edge(y)
        page.evaluate("""() => {
            document.querySelector('#changelist-form').replaceWith(window.beforeDragForm);
            window.archiveboxInitLibraryRows();
        }""")
        expect(page.locator("body")).not_to_have_class(re.compile(r"\bdragging-snapshots\b"))
        expect(page.locator(".snapshot-drag-badge,.folder-drop-target.drop-active")).to_have_count(0)
        expect(page.locator(".folder-drop-status")).to_have_text("")
        page.mouse.up()

        y = start_drag()
        move_to_edge(y)
        page.wait_for_timeout(550)
        expect(sidebar).to_be_hidden()
        expect(sidebar).to_be_visible(timeout=1400)
        assert library.evaluate("(node) => !node.classList.contains('sidebar-hidden')")
        assert page.evaluate("localStorage.getItem('archivebox.sidebar-hidden')") == "false"
        expect(child_row).to_be_hidden()
        point = parent_row.bounding_box()
        x, y = point["x"] + point["width"] / 2, point["y"] + point["height"] / 2
        page.mouse.move(x, y)
        page.mouse.move(x + 1, y)
        expect(parent_row).to_have_class(re.compile(r"\bdrop-active\b"))
        page.wait_for_timeout(250)
        expect(child_row).to_be_hidden()
        expect(child_row).to_be_visible(timeout=700)
        cancel_drag()
        assert posts == []
        browser.close()
    snapshot.refresh_from_db()
    assert snapshot.folder_id == original_folder
