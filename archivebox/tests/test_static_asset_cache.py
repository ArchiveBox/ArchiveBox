"""Versioned UI assets cache publicly and legacy URLs can revalidate."""

import gzip
from urllib.parse import urljoin

import pytest
from django.conf import settings
from django.templatetags.static import static
from django.urls import reverse
from playwright.sync_api import sync_playwright

from archivebox.machine.models import Machine
from archivebox.personas.models import Persona
from archivebox.tests.conftest import ADMIN_TEST_HOST


@pytest.mark.django_db
def test_static_asset_cache_headers(client, admin_user):
    login = client.post("/admin/login/", {"username": admin_user.username, "password": "testpassword"})
    assert login.status_code == 302
    assert settings.SESSION_COOKIE_NAME in client.cookies

    css_url = static("admin.css")
    typography_url = urljoin(css_url, "typography.css")
    font_css_url = urljoin(typography_url, "fonts/open-sans/font.css")
    font_url = urljoin(font_css_url, "latin-normal.woff2")
    immutable = "public, max-age=31536000, immutable"

    for url in (css_url, typography_url, font_css_url, font_url, static("admin/js/actions.js")):
        response = client.get(url)
        assert response.status_code == 200
        assert response["Cache-Control"] == immutable
        expected_vary = {"User-Agent", "Accept-Encoding"} if url.endswith((".css", ".js")) else {"User-Agent"}
        assert set(response["Vary"].split(", ")) == expected_vary
        etag = response["ETag"]
        modified = response["Last-Modified"]
        response.close()

        validation = client.head(url, HTTP_IF_NONE_MATCH=f"W/{etag}")
        assert validation.status_code == 304
        assert validation["ETag"] == etag
        assert validation["Cache-Control"] == immutable
        assert set(validation["Vary"].split(", ")) == expected_vary
        changed = client.head(url, HTTP_IF_NONE_MATCH='"superseded"', HTTP_IF_MODIFIED_SINCE=modified)
        assert changed.status_code == 200

    partial = client.get(font_url, HTTP_RANGE="bytes=0-3")
    assert partial.status_code == 206
    assert partial["Cache-Control"] == immutable
    assert b"".join(partial.streaming_content) == b"wOF2"

    plain = client.get(css_url)
    uncompressed_css = b"".join(plain.streaming_content)
    compressed = client.get(css_url, HTTP_ACCEPT_ENCODING="gzip")
    assert compressed["Content-Encoding"] == "gzip"
    assert compressed["Cache-Control"] == immutable
    assert compressed["ETag"] == f"W/{plain['ETag']}"
    compressed_css = b"".join(compressed.streaming_content)
    assert len(compressed_css) < len(uncompressed_css)
    assert gzip.decompress(compressed_css) == uncompressed_css
    partial = client.get(css_url, HTTP_ACCEPT_ENCODING="gzip", HTTP_RANGE="bytes=0-19")
    assert partial.status_code == 206
    assert not partial.has_header("Content-Encoding")
    assert b"".join(partial.streaming_content) == uncompressed_css[:20]

    for url in ("/static/admin.css", "/static/v/previous/admin.css", "/favicon.ico"):
        response = client.head(url)
        assert response.status_code == 200
        assert response["Cache-Control"] == "public, no-cache"
        validation = client.get(url, HTTP_IF_NONE_MATCH=response["ETag"])
        assert validation.status_code == 304
        assert validation["Cache-Control"] == "public, no-cache"


@pytest.mark.django_db
def test_admin_catalog_is_versioned_static_javascript(client, admin_user):
    url = static("admin/jsi18n.js")
    response = client.get(url)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/javascript")
    assert response["Cache-Control"] == "public, max-age=31536000, immutable"
    validation = client.head(url, HTTP_IF_NONE_MATCH=response["ETag"])
    assert validation.status_code == 304
    assert validation["Cache-Control"] == response["Cache-Control"]
    client.force_login(admin_user)
    assert response.content == client.get("/admin/jsi18n/").content


@pytest.mark.django_db
@pytest.mark.parametrize("persona_config", [False, True])
def test_add_get_compression_preserves_identity_ranges_and_privacy(client, admin_user, persona_config):
    persona = Persona.get_or_create_default()
    client.force_login(admin_user)
    query = {"persona_config": persona.name} if persona_config else {}

    plain = client.get("/add/", query, HTTP_HOST=ADMIN_TEST_HOST, HTTP_ACCEPT_ENCODING="identity")
    assert plain.status_code == 200
    assert not plain.has_header("Content-Encoding")

    compressed = client.get("/add/", query, HTTP_HOST=ADMIN_TEST_HOST, HTTP_ACCEPT_ENCODING="br, gzip")
    assert compressed.status_code == 200
    assert compressed["Content-Encoding"] == "gzip"
    assert int(compressed["Content-Length"]) == len(compressed.content) < len(plain.content)
    decoded = gzip.decompress(compressed.content)
    if persona_config:
        assert decoded == plain.content
    else:
        # Django masks the CSRF token independently on each HTML response.
        assert b'id="add-form"' in decoded
        assert b'id="add-persona-config"' in decoded

    for response in (plain, compressed):
        assert {"private", "no-store"} <= set(response["Cache-Control"].split(", "))
        assert "Accept-Encoding" in response["Vary"].split(", ")

    for headers in (
        {"HTTP_ACCEPT_ENCODING": "br"},
        {"HTTP_ACCEPT_ENCODING": "br, gzip;q=0"},
        {"HTTP_ACCEPT_ENCODING": "gzip", "HTTP_RANGE": "bytes=0-19"},
    ):
        response = client.get("/add/", query, HTTP_HOST=ADMIN_TEST_HOST, **headers)
        assert response.status_code == 200
        assert not response.has_header("Content-Encoding")


@pytest.mark.django_db
@pytest.mark.parametrize("admin_model", ["machine", "persona"])
def test_shared_admin_settings_get_compression(client, admin_user, admin_model):
    client.force_login(admin_user)
    if admin_model == "machine":
        path = reverse("admin:machine_machine_change", args=[Machine.current().pk])
    else:
        path = reverse("admin:personas_persona_change", args=[Persona.get_or_create_default().pk])

    compressed = client.get(path, HTTP_HOST=ADMIN_TEST_HOST, HTTP_ACCEPT_ENCODING="gzip")
    assert compressed.status_code == 200
    assert compressed["Content-Encoding"] == "gzip"
    assert {"private", "no-store"} <= set(compressed["Cache-Control"].split(", "))
    assert "Accept-Encoding" in compressed["Vary"].split(", ")
    decoded = gzip.decompress(compressed.content)
    assert f'id="{admin_model}_form"'.encode() in decoded
    assert b'id="plugin-settings"' in decoded
    assert len(compressed.content) < len(decoded)

    for unsupported in ("identity", "br, gzip;q=0"):
        response = client.get(path, HTTP_HOST=ADMIN_TEST_HOST, HTTP_ACCEPT_ENCODING=unsupported)
        assert response.status_code == 200
        assert not response.has_header("Content-Encoding")
        assert b'id="plugin-settings"' in response.content


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
        response = page.goto(url)
        assert response and response.status == 200
        assert response.headers["content-encoding"] == "gzip"
        assert "no-store" in response.headers["cache-control"] and "private" in response.headers["cache-control"]
        assert page.locator("#changelist-form").count() == 1
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
        for name in (
            "/admin-base.css",
            "/admin-changelist.js",
            "/progress-monitor.css",
            "/progress-monitor.js",
            "/admin.css",
            "/admin/jsi18n.js",
            "/search/field.js",
            "/search/icons.svg",
            "/library/layout.js",
            "/fonts/open-sans/latin-normal.woff2",
        ):
            assert any(path.endswith(name) for path, _ in assets), name
        assert not page.evaluate("performance.getEntriesByName(location.origin + '/admin/jsi18n/').length")
        browser.close()
