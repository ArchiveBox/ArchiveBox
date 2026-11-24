"""Versioned UI assets cache publicly and legacy URLs can revalidate."""

from urllib.parse import urljoin

import pytest
from django.templatetags.static import static
from playwright.sync_api import sync_playwright


@pytest.mark.django_db
def test_static_asset_cache_headers(client):
    css_url = static("admin.css")
    typography_url = urljoin(css_url, "typography.css")
    font_css_url = urljoin(typography_url, "fonts/open-sans/font.css")
    font_url = urljoin(font_css_url, "latin-normal.woff2")
    immutable = "public, max-age=31536000, immutable"

    for url in (css_url, typography_url, font_css_url, font_url, static("admin/js/actions.js")):
        response = client.get(url)
        assert response.status_code == 200
        assert response["Cache-Control"] == immutable
        assert response["Vary"] == "User-Agent"
        etag = response["ETag"]
        modified = response["Last-Modified"]
        response.close()

        validation = client.head(url, HTTP_IF_NONE_MATCH=f"W/{etag}")
        assert validation.status_code == 304
        assert validation["ETag"] == etag
        assert validation["Cache-Control"] == immutable
        changed = client.head(url, HTTP_IF_NONE_MATCH='"superseded"', HTTP_IF_MODIFIED_SINCE=modified)
        assert changed.status_code == 200

    partial = client.get(font_url, HTTP_RANGE="bytes=0-3")
    assert partial.status_code == 206
    assert partial["Cache-Control"] == immutable
    assert b"".join(partial.streaming_content) == b"wOF2"

    for url in ("/static/admin.css", "/static/v/previous/admin.css", "/favicon.ico"):
        response = client.head(url)
        assert response.status_code == 200
        assert response["Cache-Control"] == "public, no-cache"
        validation = client.get(url, HTTP_IF_NONE_MATCH=response["ETag"])
        assert validation.status_code == 304
        assert validation["Cache-Control"] == "public, no-cache"


@pytest.mark.django_db(transaction=True)
def test_snapshot_navigation_reuses_static_assets(browser_runtime, live_server, admin_user, snapshot):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.goto(f"{live_server.url}/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        url = f"{live_server.url}/admin/core/snapshot/"
        page.goto(url)
        page.evaluate("document.fonts.ready")
        page.goto("about:blank")
        page.goto(url)
        page.evaluate("document.fonts.ready")
        assets = page.evaluate("""() => performance.getEntriesByType('resource')
            .map(({name, transferSize}) => [new URL(name).pathname, transferSize])
            .filter(([path]) => path.startsWith('/static/'))""")
        assert assets
        assert all(path.startswith("/static/v/") and transferred == 0 for path, transferred in assets), assets
        assert len({path.split("/")[3] for path, _ in assets}) == 1
        for name in ("/admin.css", "/search/field.js", "/search/icons.svg", "/library/layout.js", "/fonts/open-sans/latin-normal.woff2"):
            assert any(path.endswith(name) for path, _ in assets), name
        browser.close()
