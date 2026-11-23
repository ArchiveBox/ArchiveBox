"""Exercise the actual mobile editor, including remounts after a streamed search."""

from urllib.parse import urlsplit

import pytest


@pytest.mark.django_db(transaction=True)
def test_operator_editor_on_phone(live_server, admin_user, crawl, browser_runtime):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Snapshot, Tag
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    tagged = Snapshot.objects.create(url="https://example.org/one", title="Tagged page", crawl=crawl)
    tagged.tags.add(Tag.objects.create(name="ABC:DEF", created_by=admin_user))
    Snapshot.objects.create(url="https://example.org/two", title="Other page", crawl=crawl)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 320, "height": 640}, is_mobile=True, has_touch=True)
        page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        field = page.get_by_role("combobox", name="Search snapshots")
        hidden = page.locator("#changelist-search [name=q]")
        field.fill('"ABC:DEF" tag:"ABC:DEF" ')
        field.press("Escape")
        field.press("Tab")
        expect(hidden).to_have_value('"ABC:DEF" tag:"ABC:DEF" ')
        expect(field.locator(".exact")).to_have_text('"ABC:DEF"')
        expect(field.locator(".exact .badge-icon")).to_have_count(0)
        expect(field.locator(".filter-badge:has(.badge-icon)")).to_have_text('tag:"ABC:DEF"')
        expect(field.locator(".badge-icon")).to_have_count(1)

        # Walk across the space back into a badged tag. Delete exactly one
        # character and undo it without disturbing the neighboring term.
        field.fill("tags:sun x")
        field.press("End")
        for key in ("ArrowLeft", "ArrowLeft", "ArrowLeft", "ArrowRight", "Backspace"):
            field.press(key)
        expect(hidden).to_have_value("tags:su x")
        field.press("Control+z")
        expect(hidden).to_have_value("tags:sun x")

        field.fill("tag")
        expect(page.locator('[role="option"] .suggestion-name')).to_have_text(["tags:"])
        field.press("Tab")
        expect(hidden).to_have_value("tags:")
        suggestion_prefixes = []

        def record_suggestion_request(request):
            from urllib.parse import parse_qs

            params = parse_qs(urlsplit(request.url).query)
            if params.get("operator") == ["tags"] and "prefix" in params:
                suggestion_prefixes.extend(params["prefix"])

        page.on("request", record_suggestion_request)
        field.press_sequentially("ABC")
        page.get_by_role("option", name="ABC:DEF", exact=True).tap()
        expect(hidden).to_have_value('tags:"ABC:DEF" ')
        assert suggestion_prefixes == ["ABC"]

        # The admin stream replaces the form. Count viewport listeners through
        # Chromium's debugger to detect a retained editor after each render.
        cdp = page.context.new_cdp_session(page)

        def viewport_listener_count():
            return cdp.send(
                "Runtime.evaluate",
                {
                    "expression": "(getEventListeners(visualViewport).resize || []).length",
                    "includeCommandLineAPI": True,
                },
            )["result"]["value"]

        before = viewport_listener_count()
        original = field.element_handle()
        field.press("Enter")
        expect(page.locator("#result_list input.action-select")).to_have_count(1)
        expect(page.get_by_role("link", name="Tagged page", exact=True)).to_be_visible()
        page.wait_for_function("original => !original.isConnected", arg=original)
        expect(field).to_be_visible()
        assert viewport_listener_count() == before
        browser.close()


@pytest.mark.django_db(transaction=True)
def test_standalone_mobile_search_submits_from_keyboard(live_server, crawl, browser_runtime):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config.update(BASE_URL=f"http://archivebox.localhost:{port}", PUBLIC_INDEX=True)
    machine.save(update_fields=["config"])
    Snapshot.objects.create(crawl=crawl, url="https://example.org", title="Mobile keyboard", config={"PERMISSIONS": "public"})

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        url = f"http://web.archivebox.localhost:{port}/public/search-field/"
        desktop = browser.new_page()
        desktop.goto(url)
        expect(desktop.get_by_role("button", name="Search", exact=True)).to_be_visible()
        for width in (320, 430, 844):
            phone = browser.new_page(viewport={"width": width, "height": 400}, is_mobile=True, has_touch=True, color_scheme="dark")
            phone.goto(url)
            expect(phone.locator('button[type="submit"]')).to_be_hidden()
            editor = phone.get_by_role("combobox", name="Search snapshots")
            expect(editor).to_have_attribute("enterkeyhint", "search")
            expect(phone.locator(".abx-query-control")).to_have_css("background-color", "rgb(255, 255, 255)")
            editor.fill('title:"Mobile keyboard"')
            editor.press("Enter")
            expect(phone.get_by_role("link", name="Mobile keyboard", exact=True)).to_be_visible()
            phone.close()
        browser.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("query", "sql_page"), [("after:2026", True), ("after:2026 AND sortable", False)])
def test_sort_search_results_by_column(live_server, admin_user, crawl, browser_runtime, query, sql_page):
    from datetime import datetime, timezone

    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    for title, year in (("Sortable Zebra", 2027), ("Sortable Alpha", 2026), ("Sortable Earlier", 2025)):
        snapshot = Snapshot.objects.create(crawl=crawl, url=f"https://example.org/{year}", title=title)
        Snapshot.objects.filter(pk=snapshot.pk).update(bookmarked_at=datetime(year, 6, 1, tzinfo=timezone.utc))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/admin/core/snapshot/")
        page.locator("[name=username]").fill(admin_user.username)
        page.locator("[name=password]").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        field = page.get_by_role("combobox", name="Search snapshots")
        field.fill(query)
        with page.expect_response(lambda response: "/search-stream/" in response.url) as stream:
            field.press("Enter")
        assert stream.value.status == 200
        assert bool(stream.value.header_value("X-ArchiveBox-Search-Page")) is sql_page
        titles = page.locator("#result_list td.field-title_str .status-fetched")
        expect(page.locator("#changelist-search")).not_to_have_attribute("aria-busy", "true")
        expect(titles).to_have_count(2)
        search_requests_after_sort = []
        page.on("request", lambda request: search_requests_after_sort.append(request.url) if "/search-stream/" in request.url else None)
        column = page.locator("#result_list th.column-title_str .text a")
        column.click()
        expect(titles).to_have_text(["Sortable Alpha", "Sortable Zebra"])
        column.click()
        expect(titles).to_have_text(["Sortable Zebra", "Sortable Alpha"])
        assert not search_requests_after_sort
        browser.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("surface", ["public", "admin"])
def test_search_toolbar_aligns_with_sidebar(live_server, admin_user, browser_runtime, surface):
    from playwright.sync_api import sync_playwright
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config.update(BASE_URL=f"http://archivebox.localhost:{port}", PUBLIC_INDEX=True)
    machine.save(update_fields=["config"])
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 830})
        if surface == "admin":
            page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/admin/core/snapshot/%3Fsidebar%3Dfolders")
            page.locator("[name=username]").fill(admin_user.username)
            page.locator("[name=password]").fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
        else:
            page.goto(f"http://web.archivebox.localhost:{port}/public/?sidebar=folders")

        editor = page.locator("#changelist-search [role=combobox]")
        for width, query, wrapped in (
            (1280, 'tags:solar title:"Solar Panel"', False),
            (834, " OR ".join(["(tags:research AND title:reports)"] * 8), True),
            (834, "tags:solar", False),
        ):
            page.set_viewport_size({"width": width, "height": 830})
            editor.fill(query)
            editor.press("Escape")
            page.wait_for_function(
                """wrapped => {
                    const bar = document.querySelector('.public-snapshot-toolbar, #changelist #toolbar');
                    const library = bar.closest('.snapshot-library');
                    const standard = parseFloat(getComputedStyle(library).getPropertyValue('--library-toolbar-height'));
                    const header = library.querySelector('.folder-section-heading').getBoundingClientRect();
                    const row = bar.getBoundingClientRect();
                    return Math.abs(row.top - header.top) < 1 && Math.abs(row.bottom - header.bottom) < 1
                        && (wrapped ? row.height > standard : Math.abs(row.height - standard) < 1);
                }""",
                arg=wrapped,
            )
        browser.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("surface", ["public", "admin"])
def test_editor_searches_only_within_active_view(live_server, admin_user, crawl, browser_runtime, surface):
    from urllib.parse import parse_qs, urlencode
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Folder, Snapshot
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config.update(BASE_URL=f"http://archivebox.localhost:{port}", PUBLIC_INDEX=True)
    machine.save(update_fields=["config"])
    folder = Folder.objects.create(name="Field notes", created_by=admin_user)
    # Each near miss differs on exactly one facet. This catches any one filter
    # being dropped even when all the other filters survive a form replacement.
    for name in ("Match", "Other result", "Wrong folder", "Wrong tag", "Wrong domain", "Wrong status", "Private"):
        host = "other.test" if name == "Wrong domain" else "notes.test"
        snapshot = Snapshot.objects.create(
            crawl=crawl,
            url=f"https://{host}/{name.replace(' ', '-')}",
            title=name,
            folder=None if name == "Wrong folder" else folder,
            status="queued" if name == "Wrong status" else "sealed",
            config={"PERMISSIONS": "private" if name == "Private" else "public"},
        )
        snapshot.save_tags(["other" if name == "Wrong tag" else "notes"])
    tag_id = Snapshot.objects.get(title="Match").tags.get().pk
    params = {"folder": str(folder.pk), "tag": str(tag_id), "domain": "notes.test"}
    if surface == "admin":
        params.update(snapshot_status="sealed", permissions="public")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        if surface == "admin":
            base = f"http://admin.archivebox.localhost:{port}/admin/core/snapshot/"
            page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/")
            page.locator("[name=username]").fill(admin_user.username)
            page.locator("[name=password]").fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
        else:
            base = f"http://web.archivebox.localhost:{port}/public/"
        page.goto(base + "?" + urlencode(params))
        editor = page.locator("#changelist-search [role=combobox]")
        rows = page.locator("#result_list tbody tr" if surface == "admin" else "#table-bookmarks tbody tr")
        expected = ["Match", "Other result"] + (["Wrong status"] if surface == "public" else [])
        expect(rows).to_have_count(len(expected))
        editor.fill("title:")
        expect(page.locator("#changelist-search [role=option] .suggestion-name")).to_have_text(expected)
        editor.fill("title:Match OR title:Wrong OR title:Private")
        editor.press("Escape")
        editor.press("Enter")
        expect(rows).to_have_count(len(expected) - 1)
        expect(rows.filter(has_text="Match")).to_have_count(1)
        # Enter on an empty editor uses a normal GET, unlike the streamed search.
        # It must restore the complete scoped list and all its active filter keys.
        page.get_by_role("button", name="Clear search", exact=True).click()
        editor.press("Escape")
        editor.press("Enter")
        expect(rows).to_have_count(len(expected))
        assert {k: v for k, v in parse_qs(urlsplit(page.url).query).items() if k in params} == {k: [v] for k, v in params.items()}
        if surface == "public":
            # A missing outlink artifact cannot keep the stream busy after all
            # candidates have been visited.
            page.set_viewport_size({"width": 320, "height": 640})
            long_query = " OR ".join(["(title:Match AND ~title:Wrong)"] * 7 + ["linksto:missing.example"])
            editor.fill(long_query)
            editor.press("Escape")
            editor.press("Enter")
            expect(rows).to_have_count(1)
            expect(page.locator(".public-snapshot-toolbar")).not_to_have_attribute("aria-busy", "true")
            expect(page.get_by_text("Showing confirmed matches", exact=False)).to_have_count(0)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert editor.evaluate("el => el.scrollHeight > el.clientHeight && el.scrollWidth <= el.clientWidth")
        browser.close()


@pytest.mark.django_db(transaction=True)
def test_progress_stays_visible_until_late_file_hit(archivebox_daemon_server, browser_runtime):
    from uuid import UUID
    from playwright.sync_api import expect, sync_playwright
    from archivebox.core.models import Snapshot
    from archivebox.tests.test_orm_helpers import use_archivebox_db
    from archivebox.crawls.models import Crawl
    from django.contrib.auth import get_user_model

    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="ripgrep", PUBLIC_INDEX="true", BASE_URL="http://archivebox.localhost")
    server.wait_for_workers(("worker_uvicorn",))
    port = server.port
    with use_archivebox_db(server.data_dir):
        owner = get_user_model().objects.create_user(username="stream-reader")
        crawl = Crawl.objects.create(urls="https://scoped.example", created_by=owner, status="sealed", retry_at=None)
        for i in range(15):
            snap = Snapshot.objects.create(
                id=UUID(int=i + 1),
                crawl=crawl,
                status="sealed",
                retry_at=None,
                url=f"https://scoped.example/{i}",
                title="Early metadata" if i == 0 else "Late content" if i == 14 else f"Unmatched {i}",
                config={"PERMISSIONS": "public"},
            )
        path = snap.output_dir / "dom" / "late.txt"
        path.parent.mkdir(parents=True)
        with path.open("wb") as stream:
            # Sparse fixture. At 4 MiB/window the final text arrives after the
            # old eight-second whole-query deadline, with no hits along the way.
            stream.seek(42 << 20)
            stream.write(b"sunrise")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.goto(f"http://web.archivebox.localhost:{port}/public/")
        editor = page.locator("#changelist-search [role=combobox]")
        editor.fill("title:Early OR deep:sunrise")
        editor.press("Escape")
        editor.press("Enter")
        rows = page.locator("#table-bookmarks tbody tr")
        expect(rows.filter(has_text="Early metadata")).to_be_visible()
        bar = page.get_by_role("progressbar", name="Searching snapshots")
        expect(bar).to_be_visible()
        expect(rows.filter(has_text="Late content")).to_be_visible(timeout=30000)
        expect(bar).to_be_hidden()
        expect(rows).to_have_count(2)
        browser.close()
