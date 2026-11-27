"""Snapshot table alignment and compact tag sizing."""

import pytest
from playwright.sync_api import Error, expect, sync_playwright

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.usefixtures("configured_single_domain_admin")
def test_snapshot_list_select_all_aligns_with_grid_toggle(browser_runtime, live_server, admin_user, crawl):
    from archivebox.core.models import Snapshot

    for index in range(2):
        Snapshot.objects.create(url=f"https://example.com/checkbox/{index}", status="sealed", crawl=crawl)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        for has_touch in (False, True):
            page = browser.new_page(viewport={"width": 1920, "height": 1000}, has_touch=has_touch)
            page.goto(f"{live_server.url}/admin/login/?next=/admin/core/snapshot/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("testpassword")
            page.locator('input[type="submit"]').click()

            controls = page.locator("#snapshot-view-toggle, #action-toggle, #result_list tbody .action-select")
            expect(controls).to_have_count(4)
            scripts = page.locator("script[src]").evaluate_all(
                "nodes => Object.fromEntries(nodes.map(node => [new URL(node.src).pathname.split('/').pop(), node.defer]))",
            )
            assert scripts.get("jsi18n.js") and scripts.get("actions.js")
            assert not any("jquery" in name or "select2" in name or "xregexp" in name for name in scripts)
            for width, sidebar_visible in ((1920, True), (1440, True), (1440, False)):
                if sidebar_visible:
                    page.set_viewport_size({"width": width, "height": 1000})
                else:
                    page.get_by_role("button", name="Hide folders", exact=True).click()
                    expect(page.locator(".folder-sidebar-reopen")).to_be_visible()
                expect(page.locator("#action-toggle")).to_be_visible()
                grid_center, *checkbox_centers = controls.evaluate_all(
                    """nodes => nodes.map(node => {
                        const rect = node.getBoundingClientRect();
                        return rect.x + rect.width / 2;
                    })""",
                )
                assert checkbox_centers == pytest.approx([grid_center] * 3, abs=0.5)
            page.close()
        browser.close()


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


@pytest.mark.usefixtures("configured_single_domain_admin")
def test_snapshot_list_tag_column_fits_title_budget(browser_runtime, live_server, admin_user, crawl):
    few_tag = create_snapshot_tag_layout_rows(crawl)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            check_snapshot_list_tag_layout(browser, live_server.url, admin_user, few_tag)
        finally:
            browser.close()


@pytest.mark.parametrize(("width", "query"), [(1440, ""), (390, ""), (1320, "?q=domain%3Aexample.com&status__exact=sealed")])
def test_snapshot_list_layout_is_stable_from_first_paint(browser_runtime, live_server, admin_user, crawl, width, query):
    create_snapshot_tag_layout_rows(crawl)
    row_count = 4
    if width == 1440:
        from archivebox.core.models import Snapshot

        for index in range(46):
            Snapshot.objects.create(
                title=f"Capture {index} with a longer title so the browser has to fit the title and tag columns",
                url=f"https://example.com/first-paint/{index}",
                status="sealed",
                crawl=crawl,
            )
        row_count = 50
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": width, "height": 900}, has_touch=width < 768)
        page.goto(f"{live_server.url}/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.evaluate(
            """hidden => {
            localStorage.setItem('archivebox.sidebar-hidden', String(hidden));
            localStorage.setItem('admin-filters-collapsed', 'false');
        }""",
            not query,
        )
        page.add_init_script("""(() => {
            const frames = window.snapshotLayoutFrames = [];
            const shifts = window.snapshotLayoutShifts = [];
            new PerformanceObserver(list => {
                for (const entry of list.getEntries()) {
                    const sources = entry.sources.map(source => source.node).filter(node => node?.closest?.('.snapshot-library'));
                    if (!entry.hadRecentInput && sources.length) {
                        shifts.push([entry.startTime, entry.value, sources.map(node => [node.tagName, node.id, node.className])]);
                    }
                }
            }).observe({type: 'layout-shift', buffered: true});
            const visible = node => node?.checkVisibility({visibilityProperty: true});
            const geometry = node => {
                if (!visible(node)) return null;
                const {x, y, width, height} = node.getBoundingClientRect();
                return [x, y, width, height].map(Math.round);
            };
            const sample = () => {
                const row = document.querySelector('#result_list tbody tr');
                if (row && !visible(row) && !window.snapshotOutlineFrame) {
                    // A wide table can take several network packets to reach its
                    // final column widths. During that interval users should
                    // already see the toolbar and the outlines of actual rows.
                    const toolbar = document.querySelector('#toolbar .abx-query-control');
                    const outline = getComputedStyle(row, '::after');
                    if (visible(toolbar) && outline.visibility === 'visible' && outline.content !== 'none' &&
                        parseFloat(outline.width) > 0 && parseFloat(outline.height) > 0) {
                        window.snapshotOutlineFrame = performance.now();
                    }
                }
                if (visible(row) && performance.getEntriesByName('first-contentful-paint').length) {
                    const state = JSON.stringify({
                        search: geometry(document.querySelector('#toolbar .abx-query-control')),
                        filter: document.querySelector('#changelist-toolbar-filter-toggle')?.getAttribute('aria-expanded'),
                        sidebar: geometry(document.querySelector('#folder-sidebar')),
                        reopen: geometry(document.querySelector('.folder-sidebar-reopen')),
                        row: geometry(row),
                        tags: geometry(document.querySelector('#result_list .column-tags_inline')),
                        counters: [...document.querySelectorAll('.library-tags-toggle')].filter(visible).map(node => node.textContent),
                        actions: geometry(document.querySelector('.actions .action-buttons')),
                        clear: geometry(document.querySelector('#toolbar .abx-query-clear')),
                    });
                    if (!frames.length) window.snapshotFirstFrame = performance.now();
                    if (frames.at(-1) !== state) frames.push(state);
                }
                requestAnimationFrame(sample);
            };
            requestAnimationFrame(sample);
        })();""")
        network = page.context.new_cdp_session(page)
        network.send("Network.enable")
        network.send("Network.setCacheDisabled", {"cacheDisabled": True})
        network.send(
            "Network.emulateNetworkConditionsByRule",
            {
                "offline": False,
                "matchedNetworkConditions": [
                    {
                        "urlPattern": f"{live_server.url}/admin/core/snapshot/",
                        "latency": 0,
                        # Leave time for Chromium to paint the streamed row
                        # outlines even if parallel CI tests delay its frames.
                        "downloadThroughput": 32 * 1024 if row_count == 50 else -1,
                        "uploadThroughput": -1,
                    },
                ],
            },
        )
        held_assets = {}
        asset_paths = ("/admin-snapshot-previews.js", "/open-sans/latin-normal.woff2")
        delayed_filter_picker = width == 390
        if delayed_filter_picker:
            asset_paths += ("/record-picker.js",)

        def hold_asset(event):
            held_assets[event["requestId"]] = event["request"]["url"]

        network.on("Fetch.requestPaused", hold_asset)
        network.send(
            "Fetch.enable",
            {"patterns": [{"urlPattern": f"*{path}*"} for path in asset_paths]},
        )
        page.goto(f"{live_server.url}/admin/core/snapshot/{query}", wait_until="commit")
        expect(page.locator("#changelist-search .query")).to_be_visible(timeout=15000)
        expect(page.locator("#result_list tbody tr")).to_have_count(row_count, timeout=15000)
        if not delayed_filter_picker:
            page.wait_for_load_state("domcontentloaded")

        page.wait_for_function("window.snapshotLayoutFrames.length > 0")
        assert all(any(path in url for url in held_assets.values()) for path in asset_paths)
        first_frame = page.evaluate("JSON.parse(window.snapshotLayoutFrames[0])")
        if row_count == 50:
            assert page.evaluate("window.snapshotOutlineFrame > 0 && window.snapshotOutlineFrame < window.snapshotFirstFrame")

        # Release the actual assets only after the fallback-font list has painted.
        # On phones the filter picker must not shift the stacked filter panel.
        for request_id in tuple(held_assets):
            try:
                network.send("Fetch.continueRequest", {"requestId": request_id})
            except Error as error:
                # A request Chromium canceled is no longer paused. The
                # successful post-paint response for each asset is checked below.
                if "Protocol error (Fetch.continueRequest): Invalid InterceptionId." not in str(error):
                    raise
        network.send("Fetch.disable")
        page.wait_for_load_state("load")
        page.evaluate(
            "async () => { await document.fonts.ready; await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); }",
        )
        frames = page.evaluate("window.snapshotLayoutFrames.map(JSON.parse)")
        assert frames[-1]["search"]
        assert frames[-1]["counters"]
        assert frames[-1]["actions"] is None
        assert bool(frames[-1]["clear"]) == bool(query)
        assert page.evaluate("window.snapshotLayoutShifts") == []
        assert frames == [first_frame]
        assert page.evaluate(
            """paths => paths.every(path => performance.getEntriesByType('resource').some(entry =>
                entry.name.includes(path) && entry.responseStatus === 200 && entry.responseEnd > window.snapshotFirstFrame
            ))""",
            asset_paths,
        )
        browser.close()
