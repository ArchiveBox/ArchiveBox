"""Browser checks for native domain capture filter controls."""

from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from archivebox.crawls.models import Crawl
from archivebox.machine.models import Machine
from archivebox.core.models import Snapshot


@pytest.mark.django_db(transaction=True)
def test_domain_counts_match_before_and_after_pagination(live_server, browser_runtime, admin_user):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    crawl = Crawl.objects.create(urls="https://claude.ai/", created_by=admin_user)
    Snapshot.objects.bulk_create(
        [Snapshot(crawl=crawl, url=f"https://claude.ai/{index}", timestamp=str(1921000000 + index)) for index in range(79)],
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page()
            page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/admin/domains/")
            page.locator('[name="username"]').fill(admin_user.username)
            page.locator('[name="password"]').fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            count = page.locator('.field-count a[href*="claude.ai"]')
            expect(count).to_have_text("79")
            count.click()
            paginator = page.locator(".paginator").last
            expect(paginator).to_contain_text("79 snapshots")
            expect(paginator).not_to_contain_text("+")
            expect(paginator).not_to_contain_text("≈")
            paginator.get_by_role("link", name="Next", exact=True).click()
            expect(paginator).to_contain_text("79 snapshots")
            expect(paginator.get_by_role("link", name="Next", exact=True)).to_have_count(0)
            paginator.get_by_role("link", name="Previous", exact=True).click()
            expect(paginator).to_contain_text("79 snapshots")
            search = page.get_by_role("combobox", name="Search snapshots", exact=True)
            search.fill("domain:claude.ai")
            search.press("Enter")
            expect(paginator).to_contain_text("79 snapshots")
            page.locator("th.column-title_str .text a").click()
            paginator.get_by_role("link", name="Next", exact=True).click()
            expect(page.locator("#result_list input.action-select")).to_have_count(29)
            query = parse_qs(urlsplit(page.url).query)
            assert query["domain"] == ["*.claude.ai"]
            assert query["q"] == ["domain:claude.ai"]
            assert query["p"] == ["2"] and "o" in query
            page.get_by_role("button", name="Switch to grid view", exact=True).click()
            expect(page.get_by_role("button", name="Switch to list view", exact=True)).to_be_visible()
            assert parse_qs(urlsplit(page.url).query) == query
            expect(paginator).to_contain_text("79 snapshots")
            page.get_by_role("button", name="Switch to list view", exact=True).click()
            expect(page.get_by_role("button", name="Switch to grid view", exact=True)).to_be_visible()
            assert parse_qs(urlsplit(page.url).query) == query
            expect(page.locator("#result_list input.action-select")).to_have_count(29)
        finally:
            browser.close()


@pytest.mark.django_db(transaction=True)
def test_domain_scope_controls_and_blank_allowlist(live_server, browser_runtime, admin_user):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/newest", created_by=admin_user)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page()
            page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/admin/domains/")
            page.locator('[name="username"]').fill(admin_user.username)
            page.locator('[name="password"]').fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.locator("#id_url").fill("https://news.ycombinator.com/newest")
            page.locator("#site-add-button").click()
            same_domain = page.locator('[name="url_filters_same_domain_only"]')
            subdomains = page.locator('[name="include_subdomains"]')
            expect(same_domain).to_be_checked()
            subdomains.check()
            expect(same_domain).not_to_be_checked()
            same_domain.check()
            expect(subdomains).not_to_be_checked()
            page.locator('[name="url_filters_subpaths_only"]').check()
            page.locator(".url-filter-patterns > summary").click()
            page.locator('[name="url_filters_allowlist"]').fill("\n ")
            options = parse_qs(urlsplit(page.locator("#site-more-options").get_attribute("href")).query)
            patterns = Crawl.split_filter_patterns(options["url_filters_allowlist"][0])
            assert patterns
            assert crawl.url_passes_compiled_filters("https://news.ycombinator.com/newest", allowlist=patterns, denylist=[])
            assert crawl.url_passes_compiled_filters("https://news.ycombinator.com/sitemap.xml", allowlist=patterns, denylist=[])
            assert not crawl.url_passes_compiled_filters("https://other.example/newest", allowlist=patterns, denylist=[])
            assert not crawl.url_passes_compiled_filters("https://news.ycombinator.com/unrelated", allowlist=patterns, denylist=[])
        finally:
            browser.close()
