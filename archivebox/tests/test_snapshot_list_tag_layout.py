"""Real table and compact Snapshot tag sizing."""

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.django_db(transaction=True)


def create_snapshot_tag_layout_rows(crawl):
    from archivebox.core.models import Snapshot, Tag

    few_tag = None
    for key, count in (("Crowded", 18), ("Short", 10), ("Few", 2), ("Empty", 0)):
        snapshot = Snapshot.objects.create(
            title=f"Column sizing {key}",
            url=f"https://example.com/column-sizing/{key.lower()}",
            status="sealed",
            crawl=crawl,
        )
        prefix = "T" if key == "Short" else key
        tags = [Tag.objects.create(name=f"{prefix} {index:02d}") for index in range(count)]
        snapshot.tags.set(tags)
        if key == "Few":
            few_tag = tags[0].pk
    return few_tag


def check_snapshot_list_tag_layout(browser, origin, admin_user, few_tag):
    page = browser.new_page(viewport={"width": 1920, "height": 1000})
    page.goto(f"{origin}/admin/login/")
    page.locator("#id_username").fill(admin_user.username)
    page.locator("#id_password").fill("testpassword")
    page.locator('input[type="submit"]').click()

    def read_widths():
        return page.locator("#result_list thead th").evaluate_all(
            "(nodes) => Object.fromEntries(nodes.map(n => [n.className.split(' ').find(c => c.startsWith('column-')) || n.className, n.getBoundingClientRect().width]))",
        )

    def navigate(query=""):
        page.goto(f"{origin}/admin/core/snapshot/?{query}")
        page.evaluate("document.fonts.ready")

    def row(key):
        return page.locator("#result_list tbody tr").filter(has_text=f"Column sizing {key}")

    # With two tags, the table should not reserve 40% for largely empty space.
    navigate(f"tags__id__exact={few_tag}")
    expect(row("Few").locator(".tag-pill:visible")).to_have_count(2)
    expect(row("Few").locator(".library-tags-toggle")).to_be_hidden()
    narrow_demand = read_widths()

    navigate()
    for width in (2560, 1920, 1440, 1160, 1100):
        page.set_viewport_size({"width": width, "height": 1000})
        expect(row("Crowded").locator(".library-tags-toggle")).to_be_visible()
        page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        if width == 1100:
            expect(page.locator("#result_list thead")).to_be_hidden()
            expect(row("Crowded").locator(".tag-pill:visible")).to_have_count(2)
            expect(row("Crowded").locator(".library-tags-toggle")).to_have_text("+16")
            expect(row("Few").locator(".tag-pill:visible")).to_have_count(2)
            assert page.locator("#changelist-form > .results").evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            continue
        cols = read_widths()
        tag_width, title_width = cols["column-tags_inline"], cols["column-title_str"]
        assert tag_width <= 0.4 * (tag_width + title_width) + 2
        assert title_width >= 0.6 * (tag_width + title_width) - 2
        if width == 1920:
            assert tag_width >= 0.35 * (tag_width + title_width)
            assert tag_width > narrow_demand["column-tags_inline"] + 100
            for key in cols.keys() - {"column-tags_inline", "column-title_str"}:
                assert abs(cols[key] - narrow_demand[key]) <= 2, (key, cols, narrow_demand)
        few_shown = row("Few").locator(".tag-pill:visible").count()
        if width >= 1440:
            assert few_shown == 2
        if few_shown < 2:
            expect(row("Few").locator(".library-tags-toggle")).to_have_text(f"+{2 - few_shown}")
        expect(row("Empty").locator(".library-tags-toggle")).to_be_hidden()
        if width == 1160:
            short_shown = row("Short").locator(".tag-pill:visible").count()
            assert short_shown == 1
            expect(row("Short").locator(".library-tags-toggle")).to_have_text("+9")
        crowded = row("Crowded")
        pills = crowded.locator(".tag-pill:visible")
        count = pills.count()
        assert 1 <= count < 18
        if width >= 1920:
            assert count > 2
        if width == 2560:
            assert count >= 5
        expect(crowded.locator(".library-tags-toggle")).to_have_text(f"+{18 - count}")
        assert pills.evaluate_all("""pills => {
            if (!pills.length) return true;
            const cell = pills[0].closest("td").getBoundingClientRect();
            const container = pills[0].parentElement.getBoundingClientRect();
            const line = pills[0].getBoundingClientRect().top;
            return pills.every(pill => {
                const rect = pill.getBoundingClientRect();
                return Math.abs(rect.top - line) < 1 && rect.right <= Math.min(cell.right, container.right) + 1;
            });
        }""")

    crowded = row("Crowded")
    crowded.locator(".library-tags-toggle").click()
    expect(crowded.locator(".tag-pill:visible")).to_have_count(18)
    crowded.locator(".library-tags-toggle").click()
    expect(crowded.locator(".library-tags-toggle")).to_have_attribute("aria-expanded", "false")
    visible = crowded.locator(".tag-pill:visible").count()
    expect(crowded.locator(".library-tags-toggle")).to_have_text(f"+{18 - visible}")

    # Compact mobile layout retains its independent two-pill behavior.
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator("#result_list thead")).to_be_hidden()
    expect(crowded.locator(".tag-pill:visible")).to_have_count(2)
    expect(crowded.locator(".library-tags-toggle")).to_have_text("+16")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    # The native inline edit repaints and recomputes the collapsed counter.
    page.set_viewport_size({"width": 1920, "height": 1000})
    tag_input = crowded.locator(".tag-inline-input-sm")
    tag_input.focus()
    expect(crowded.locator(".tag-pill:visible")).to_have_count(18)
    expect(crowded.locator(".library-tags-toggle")).to_be_hidden()
    tag_input.fill("Sizing new tag")
    tag_input.press("Enter")
    expect(crowded.locator('.tag-pill[data-tag="Sizing new tag"]')).to_have_count(1)
    tag_input.blur()
    expect(crowded.locator(".library-tags-toggle")).to_be_visible()
    visible = crowded.locator(".tag-pill:visible").count()
    expect(crowded.locator(".library-tags-toggle")).to_have_text(f"+{19 - visible}")
    page.close()


def test_snapshot_list_tag_column_fits_title_budget(browser_runtime, live_server, admin_user, crawl):
    few_tag = create_snapshot_tag_layout_rows(crawl)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            check_snapshot_list_tag_layout(browser, live_server.url, admin_user, few_tag)
        finally:
            browser.close()
