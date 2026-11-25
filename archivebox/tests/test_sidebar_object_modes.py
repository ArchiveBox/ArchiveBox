"""Exercise object sidebar modes through the native Snapshot library UI."""

from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import pytest
from django.urls import reverse
from django.utils import timezone

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.importers.catalog import get_importer_providers, get_importers
from archivebox.importers.models import ImporterRun, ImporterSource
from archivebox.machine.models import Machine
from archivebox.personas.models import Persona
from archivebox.tests.test_snapshot_exports import exported_body_ids


@pytest.mark.django_db(transaction=True)
def test_snapshot_object_sidebar_modes_in_browser(live_server, admin_user, browser_runtime):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.sidebar import INITIAL_FOLDER_PAGE_SIZE

    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}",
        "PUBLIC_INDEX": True,
    }
    machine.save(update_fields=["config"])

    def new_crawl(**kwargs):
        return Crawl.objects.create(created_by=admin_user, urls="https://example.test/", **kwargs)

    def new_snapshot(crawl, slug, title):
        return Snapshot.objects.create(crawl=crawl, url=f"https://example.test/{slug}", title=title, config={"PERMISSIONS": "public"})

    persona = Persona.objects.create(name="Collection research", created_by=admin_user, config={"PERMISSIONS": "private"})
    persona_crawl = new_crawl(persona=persona)
    persona_snapshot = new_snapshot(persona_crawl, "persona-match", "Collection Needle")
    new_snapshot(persona_crawl, "persona-unmatched", "Different topic")
    new_snapshot(new_crawl(), "other-persona", "Collection Needle")

    provider = next(row for row in get_importer_providers(get_importers()) if row["definition"].plugin == "importer_rss")
    definition = provider["definition"]
    importer = ImporterSource.objects.create(
        created_by=admin_user,
        name="Saved feed for sidebar",
        plugin=definition.plugin,
        feed=definition.feed,
    )
    imported_crawl = new_crawl()
    imported_snapshot = new_snapshot(imported_crawl, "imported-match", "Collection Needle")
    ImporterRun.objects.create(source=importer, crawl=imported_crawl, status=ImporterRun.Status.SUCCEEDED)
    family_id = f"importer-family:{definition.plugin}:{definition.feed}"

    first_run = new_crawl(created_at=timezone.now() - timedelta(days=5))
    schedule = CrawlSchedule.objects.create(created_by=admin_user, label="Collection monitoring", template=first_run, schedule="@daily")
    first_run_snapshot = new_snapshot(first_run, "first-run", "Collection Needle")
    now = timezone.now()
    later_runs = Crawl.objects.bulk_create(
        [
            Crawl(created_by=admin_user, urls="https://example.test/", schedule=schedule, created_at=now + timedelta(minutes=number))
            for number in range(INITIAL_FOLDER_PAGE_SIZE + 1)
        ],
    )
    related_snapshot = new_snapshot(later_runs[-1], "later-run", "Collection Needle")

    origin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    base = reverse("admin:core_snapshot_changelist")
    search = "title:Needle"
    view = f"{base}?{urlencode({'q': search})}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=browser_runtime["chrome_args"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{origin}/admin/login/?next={base}")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.goto(origin + view)
        sidebar = page.locator("#folder-sidebar")
        expect(sidebar).to_be_visible()

        def choose(label, mode):
            sidebar.get_by_role("button", name="Choose sidebar view").click()
            sidebar.get_by_role("menuitem", name=label, exact=True).click()
            expect(sidebar).to_have_attribute("data-mode", mode)
            assert parse_qs(urlsplit(page.url).query)["q"] == [search]

        def row(pk):
            return sidebar.locator(f'.library-object-row[data-folder-id="{pk}"]')

        def action_menu(entry):
            entry.hover()
            entry.get_by_role("button", name="Actions for", exact=False).click()
            return entry.locator(".folder-menu:popover-open")

        def select(entry, parameter, pk, expected_snapshots):
            entry.locator("a.library-link").click()
            expect(sidebar.locator(f'.library-object-row[data-folder-id="{pk}"] a[aria-current="page"]')).to_be_visible()
            query = parse_qs(urlsplit(page.url).query)
            assert query[parameter] == [str(pk)] and query["q"] == [search]
            footer = sidebar.locator(".folder-actions")
            footer.get_by_role("button", name="Export", exact=True).click()
            menu = footer.get_by_role("menu", name="Export current view")
            csv_path = menu.get_by_role("menuitem", name="CSV", exact=True).get_attribute("href")
            csv_query = parse_qs(urlsplit(csv_path).query)
            assert csv_query[parameter] == [str(pk)] and csv_query["q"] == [search]
            exported = page.request.get(urljoin(page.url, csv_path))
            assert exported.ok
            assert exported_body_ids(exported.body(), "csv") == {str(snapshot.pk) for snapshot in expected_snapshots}
            page.keyboard.press("Escape")

        choose("Personas", "personas")
        add_persona = sidebar.get_by_role("link", name="Add Persona", exact=True)
        expect(add_persona).to_have_attribute("href", reverse("admin:personas_persona_add"))
        sidebar.get_by_role("button", name="Find a persona").click()
        sidebar.get_by_role("searchbox", name="Find a persona").fill(persona.name)
        expect(sidebar.locator(".library-object-row")).to_have_count(1)
        menu = action_menu(row(persona.pk))
        expect(menu.get_by_role("menuitem", name="Edit", exact=True)).to_have_attribute(
            "href",
            reverse("admin:personas_persona_change", args=[persona.pk]),
        )
        page.keyboard.press("Escape")
        select(row(persona.pk), "persona", persona.pk, [persona_snapshot])

        choose("Importers", "importers")
        sidebar.get_by_role("button", name="New importer", exact=True).click()
        new_menu = sidebar.get_by_role("menu", name="New importer", exact=True)
        native_add = reverse("importers:new", args=[definition.plugin, definition.feed])
        expect(new_menu.locator(f'a[href="{native_add}"]')).to_be_visible()
        page.keyboard.press("Escape")
        expect(row(importer.pk)).to_have_count(0)
        row(family_id).locator("button.library-branch-label").click()
        expect(row(importer.pk)).to_be_visible()
        menu = action_menu(row(importer.pk))
        for route, name in [("importers:detail", "Open importer"), ("importers:edit", "Edit importer")]:
            expect(menu.get_by_role("menuitem", name=name, exact=True)).to_have_attribute("href", reverse(route, args=[importer.pk]))
        page.keyboard.press("Escape")
        select(row(importer.pk), "importer", importer.pk, [imported_snapshot])

        choose("Scheduled Crawls", "scheduled-crawls")
        expect(sidebar.get_by_role("link", name="New Scheduled Crawl", exact=True)).to_have_attribute(
            "href",
            reverse("admin:crawls_crawlschedule_add"),
        )
        menu = action_menu(row(schedule.pk))
        expect(menu.get_by_role("menuitem", name="Edit", exact=True)).to_have_attribute(
            "href",
            reverse("admin:crawls_crawlschedule_change", args=[schedule.pk]),
        )
        page.keyboard.press("Escape")
        toggle = row(schedule.pk).locator(".folder-toggle")
        if toggle.get_attribute("aria-expanded") == "false":
            toggle.click()
        expect(row(later_runs[-1].pk)).to_be_visible()
        expect(row(first_run.pk)).to_have_count(0)
        more = sidebar.locator(f'.library-child-more[data-parent="{schedule.pk}"]')
        with page.expect_response(
            lambda response: "cursor" in (params := parse_qs(urlsplit(response.url).query)) and params.get("parent") == [str(schedule.pk)],
        ) as next_page:
            more.scroll_into_view_if_needed()
        assert next_page.value.ok
        expect(row(first_run.pk)).to_be_visible()
        page.goto(origin + view)
        choose("Scheduled Crawls", "scheduled-crawls")
        select(row(schedule.pk), "crawl_schedule", schedule.pk, [first_run_snapshot, related_snapshot])

        toggle = row(schedule.pk).locator(".folder-toggle")
        if toggle.get_attribute("aria-expanded") == "false":
            toggle.click()
        expect(row(later_runs[-1].pk)).to_be_visible()
        select(row(later_runs[-1].pk), "crawl", later_runs[-1].pk, [related_snapshot])
        browser.close()
