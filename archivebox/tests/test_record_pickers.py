import pytest
from django.urls import reverse
from django.test import Client

from archivebox.core.models import Folder
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def test_folder_picker_search_is_bounded_and_respects_destination_rules(admin_client, django_user_model):
    root = Folder.objects.create(name="👩🏽‍💻 Archive")
    child = Folder.objects.create(name="🗂️ 2026", parent=root)
    smart = Folder.objects.create(name="Smart result", rules={"field": "url", "lookup": "icontains", "value": "example.com"})
    Folder.objects.bulk_create([Folder(name=f"Result {i:02}") for i in range(35)])
    endpoint = "/api/v1/core/folders/autocomplete/"
    client = Client()
    assert client.get(endpoint, HTTP_HOST=ADMIN_TEST_HOST).status_code == 401
    client.force_login(django_user_model.objects.create_user("staff-without-folder-access", is_staff=True))
    assert client.get(endpoint, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403

    def lookup(**params):
        response = admin_client.get(endpoint, params, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200, response.content
        return response.json()

    first = lookup(q="result")
    assert len(first["choices"]) == 20
    next_page = lookup(q="result", after=first["next"])
    assert len({item["id"] for item in first["choices"] + next_page["choices"]}) == 36
    assert {item["id"] for item in lookup(q="smart")["choices"]} == {str(smart.pk)}
    assert not lookup(q="smart", destination="true")["choices"]
    assert {"id": str(child.pk), "name": "👩🏽‍💻 Archive / 🗂️ 2026"} in lookup(q="2026")["choices"]
    assert lookup(q="Archive / 2026")["choices"] == [{"id": str(child.pk), "name": "👩🏽‍💻 Archive / 🗂️ 2026"}]
    assert not lookup(q="2026", exclude=str(root.pk))["choices"]


def test_rules_and_add_only_render_saved_folder_options(admin_client):
    root = Folder.objects.create(name="Unused Folder")
    editor = admin_client.get(reverse("rules:data"), HTTP_HOST=ADMIN_TEST_HOST)
    assert editor.status_code == 200
    assert str(root.pk) not in editor.content.decode()
    response = admin_client.get("/add/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert f'value="{root.pk}"'.encode() not in response.content


def test_folder_picker_moves_snapshot_at_mobile_width(live_server, browser_runtime, admin_user, snapshot):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    parent = Folder.objects.create(name="👩🏽‍💻 Research")
    destination = Folder.objects.create(name="📚 Reading", parent=parent)
    smart = Folder.objects.create(name="Reading smart", rules={"field": "url", "lookup": "icontains", "value": "example"})
    admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
            page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.locator(f'input.action-select[value="{snapshot.pk}"]').check()
            picker = page.locator('.record-picker:has(select[name="folder_destination"])')
            menu = picker.get_by_role("combobox")
            menu.tap()
            expect(picker.get_by_role("searchbox")).to_be_hidden()
            page.keyboard.press("Escape")
            menu.select_option(label="Find a folder…")
            picker.get_by_role("searchbox").fill("Reading")
            choices = picker.locator("select")
            expect(choices.locator(f'option[value="{destination.pk}"]')).to_have_text("👩🏽‍💻 Research / 📚 Reading")
            expect(choices.locator(f'option[value="{smart.pk}"]')).to_have_count(0)
            choices.select_option(str(destination.pk))
            expect(page.locator(".messagelist")).to_contain_text("Moved 1 snapshot(s) to 📚 Reading")
        finally:
            browser.close()

    snapshot.refresh_from_db()
    assert snapshot.folder_id == destination.pk


def test_folder_picker_on_admin_forms_and_add(live_server, browser_runtime, admin_user, snapshot):
    import os
    import re
    from pathlib import Path
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.machine.models import Machine
    from archivebox.personas.models import Persona

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    root = Folder.objects.create(name="Nested")
    regular = Folder.objects.create(name="Shared shelf", parent=root)
    Folder.objects.create(name="Shared shelf", parent=Folder.objects.create(name="Research"))
    smart = Folder.objects.create(name="Shared rule", rules={"query": "title:Shared"})
    persona = Persona.objects.create(name="Picker audit")
    admin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.goto(f"{admin}/admin/login/")
        page.get_by_label("Username").fill(admin_user.username)
        page.get_by_label("Password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        for path, selector, destinations in (
            ("/add/", "#id_folder", True),
            (reverse("admin:core_snapshot_change", args=[snapshot.pk]), "#id_folder", True),
            (reverse("admin:crawls_crawl_change", args=[snapshot.crawl_id]), "#id_folder", True),
            (reverse("admin:core_folder_change", args=[root.pk]), "#id_parent", False),
        ):
            assert page.goto(admin + path).ok
            select = page.locator(selector)
            select.click()
            picker = select.locator("..")
            search = picker.get_by_role("searchbox", name="Find a folder")
            expect(search).to_be_focused()
            with page.expect_response(lambda response: "/folders/autocomplete/" in response.url and "q=Shared" in response.url) as response:
                search.fill("Shared")
            assert response.value.ok and ("destination=true" in response.value.url) == destinations
            choice = smart.name if not destinations else "Nested / Shared shelf"
            button = picker.get_by_role("button", name=choice, exact=True)
            expect(button).to_be_visible()
            expect(picker.get_by_role("button", name=smart.name, exact=True)).to_have_count(0 if destinations else 1)
            button.click()
            expect(select).to_have_value(str(regular.pk if destinations else smart.pk))
        page.goto(admin + reverse("admin:core_snapshot_changelist"))
        page.locator(f'input.action-select[value="{snapshot.pk}"]').check()
        move = page.get_by_role("combobox", name="Move to folder", exact=True)
        move.click()
        search = page.get_by_role("searchbox", name="Find a folder", exact=True)
        expect(search).to_be_focused()
        search.fill("Shared")
        destination = page.get_by_role("button", name="Nested / Shared shelf", exact=True)
        expect(destination).to_be_visible()
        expect(move).to_have_value("__choose__")
        if output := os.environ.get("ARCHIVEBOX_UI_SCREENSHOT_DIR"):
            panel = destination.locator("../..").bounding_box()
            control = move.bounding_box()
            left = max(0, min(panel["x"], control["x"]) - 200)
            top = min(panel["y"], control["y"]) - 12
            page.screenshot(
                path=str(Path(output) / "desktop-folder-search.png"),
                clip={
                    "x": left,
                    "y": top,
                    "width": min(660, page.viewport_size["width"] - left),
                    "height": max(panel["y"] + panel["height"], control["y"] + control["height"]) - top + 16,
                },
            )
        search.press("Escape")
        expect(move).to_have_value("__choose__")
        # The list filter includes Smart Folders and applies the chosen ID.
        page.locator("#changelist-toolbar-filter-toggle").click()
        filter_control = page.locator('select[data-picker-filter="folder"]')
        filter_control.click()
        search.fill("Shared")
        page.get_by_role("button", name=smart.name, exact=True).click()
        expect(page).to_have_url(re.compile(f"folder={smart.pk}"))

        assert page.goto(admin + reverse("admin:personas_persona_change", args=[persona.pk])).ok
        expect(page.locator("#persona_form")).to_be_visible()
        # Persona configures browser profiles. Filesystem paths are not archive folder IDs.
        expect(page.locator('#persona_form select[data-picker="folder"], #persona_form select[name="folder"]')).to_have_count(0)
        browser.close()


def test_folder_picker_orders_matching_branches_across_pages(admin_client):
    root = Folder.objects.create(name="Match Z root", position=9)
    parent = root
    for depth in range(5):
        parent = Folder.objects.create(name=f"Match A level {depth}", parent=parent)
    leaves = [Folder(name=f"Match A leaf {i:02d}", parent=parent) for i in range(34)]
    leaves.extend(Folder(name=f"Match {name}", parent=parent) for name in ("Study", "study", "École", "🔖"))
    Folder.objects.bulk_create(leaves)
    smart = Folder.objects.create(name="Match Smart", parent=parent, rules={"query": "title:science"})
    Folder.objects.create(name="Match other root", position=10)
    expected = [(str(pk), label) for pk, label in Folder.path_choices() if "Match" in label]

    def pages(**filters):
        params = {"q": "Match", **filters}
        choices = []
        while True:
            response = admin_client.get(reverse("api-1:folders_autocomplete"), params, HTTP_HOST=ADMIN_TEST_HOST)
            assert response.status_code == 200, response.content
            page = response.json()
            assert len(page["choices"]) <= 20
            choices.extend((item["id"], item["name"]) for item in page["choices"])
            if not page["next"]:
                return choices
            assert params.get("after") != page["next"]
            params["after"] = page["next"]

    assert pages() == expected
    assert pages(destination="true") == [choice for choice in expected if choice[0] != str(smart.pk)]
    assert pages(exclude=str(root.pk)) == [expected[-1]]


def test_folder_picker_large_hierarchy_in_browser(live_server, browser_runtime, admin_user, record_property, client, crawl):
    from time import perf_counter
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.smart_folders import CHILDREN_RULES
    from archivebox.machine.models import Machine

    roots = [Folder(name=f"Root {i:02}", rules=CHILDREN_RULES) for i in range(10)]
    rows = list(roots)
    for root in roots:
        for branch in range(10):
            parent = root
            for level in range(5):
                parent = Folder(name=f"Level {level} branch {branch}", parent=parent, rules=CHILDREN_RULES)
                rows.append(parent)
            for leaf in range(100):
                query = "title:research" if leaf == 1 else f"title:topic-{root.name[-2:]}-{branch}-{leaf}"
                rows.append(Folder(name=f"Leaf {leaf:02}", parent=parent, rules={"query": query} if leaf % 2 else None))
    Folder.objects.bulk_create(rows, batch_size=100)
    from archivebox.core.models import Snapshot
    from archivebox.tests.conftest import WEB_TEST_HOST

    Snapshot.objects.create(crawl=crawl, url="https://research.example.org", title="Research", config={"PERMISSIONS": "public"})
    Machine.from_json({"config": {"PUBLIC_INDEX": True}})
    started = perf_counter()
    response = client.get(
        reverse("search-suggestions"),
        {"operator": "folder", "prefix": "Leaf 01", "search_url": reverse("public-index")},
        HTTP_HOST=WEB_TEST_HOST,
    )
    assert response.status_code == 200
    public_paths = response.json()["values"]
    assert len(public_paths) == 20
    assert all(path.endswith(" / Leaf 01") for path in public_paths)
    record_property("public_folder_suggestions_ms", round(1000 * (perf_counter() - started)))
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    admin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.goto(admin + "/admin/login/?next=/add/")
        page.get_by_label("Username").fill(admin_user.username)
        page.get_by_label("Password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        select = page.locator("#id_folder")
        picker = select.locator("..")
        select.click()
        buttons = picker.locator(".record-picker-choices button")
        expect(buttons).to_have_count(21)  # 20 choices plus No folder
        expect(buttons.nth(1)).to_have_text("Root 00")
        expect(buttons.nth(2)).to_have_text("Root 00 / Level 0 branch 0")
        previous = set(buttons.all_text_contents())
        for _ in range(3):
            with page.expect_response(lambda r: "/folders/autocomplete/" in r.url and "after=" in r.url) as reply:
                picker.get_by_role("button", name="More results").click()
            labels = [choice["name"] for choice in reply.value.json()["choices"]]
            expect(buttons.last).to_have_text(labels[-1])
            assert previous.isdisjoint(labels)
            previous.update(labels)
            assert len(reply.value.body()) < 8192
            assert select.locator("option").count() <= 23

        start = perf_counter()
        with page.expect_response(lambda r: "/folders/autocomplete/" in r.url and "q=Leaf" in r.url) as reply:
            picker.get_by_role("searchbox").fill("Leaf 98")
        labels = [choice["name"] for choice in reply.value.json()["choices"]]
        expect(buttons.first).to_have_text(labels[0])
        record_property("filter_to_visible_ms", round(1000 * (perf_counter() - start)))
        record_property("response_bytes", len(reply.value.body()))
        assert len(labels) == 20
        assert labels[0].startswith("Root 00 / Level 0 branch 0 /") and labels[0].endswith(" / Leaf 98")
        assert labels[1].startswith("Root 00 / Level 0 branch 1 /")
        buttons.first.click()
        expect(select).to_have_value(reply.value.json()["choices"][0]["id"])
        browser.close()
