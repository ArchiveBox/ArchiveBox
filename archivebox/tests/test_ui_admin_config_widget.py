from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory

from archivebox.base_models.admin import KeyValueWidget
from archivebox.config.common import get_config
from archivebox.core.middleware import AdminCookieIsolationMiddleware
from archivebox.core.setup_wizard import get_base_url_mismatch_context, get_setup_wizard_context
from archivebox.core.templatetags.core_tags import system_warnings_banner
from archivebox.core.views import HealthCheckView

STATIC_DIR = Path(__file__).parents[1] / "templates" / "static"
SETUP_WIZARD_CSS = (STATIC_DIR / "setup_wizard.css").read_text()
SETUP_WIZARD_JS = (STATIC_DIR / "setup_wizard.js").read_text()


def test_key_value_widget_renders_enum_autocomplete_metadata():
    html = str(
        KeyValueWidget().render(
            "config",
            {"CHROME_WAIT_FOR": "load"},
            attrs={"id": "id_config"},
        ),
    )

    assert '"enum": ["domcontentloaded", "load", "networkidle0", "networkidle2"]' in html
    assert 'class="kv-value-options"' in html
    assert 'class="kv-help"' in html
    assert "configureValueInput_id_config" in html
    assert "describeMeta_id_config" in html
    assert "validateValueAgainstMeta_id_config" in html


def test_key_value_widget_renders_numeric_and_pattern_constraints():
    html = str(KeyValueWidget().render("config", {}, attrs={"id": "id_config"}))

    assert '"minimum": 0' in html
    assert '"pattern": "^\\\\d+,\\\\d+$"' in html
    assert "Expected: " in html
    assert "Example: " in html
    assert "setValueValidationState_id_config" in html
    assert "coerceValueForStorage_id_config" in html


def test_key_value_widget_accepts_common_boolean_spellings():
    html = str(KeyValueWidget().render("config", {"CHECK_SSL_VALIDITY": "True"}, attrs={"id": "id_config"}))

    assert "enumValues = ['True', 'False']" in html
    assert "raw.toLowerCase()" in html
    assert "lowered === 'true' || raw === '1'" in html
    assert "lowered === 'false' || raw === '0'" in html


def test_key_value_widget_shows_array_and_object_examples_and_binary_rules():
    html = str(KeyValueWidget().render("config", {"NODE_BINARY": "node"}, attrs={"id": "id_config"}))

    assert 'Example: ["--extra-arg"]' in html
    assert "Example: wget or /usr/bin/wget" in html
    assert "validateBinaryValue_id_config" in html
    assert "meta.key.endsWith('_BINARY')" in html
    assert "Binary paths cannot contain quotes" in html


def test_key_value_widget_falls_back_to_binary_validation_for_unknown_binary_keys():
    html = str(
        KeyValueWidget().render(
            "config",
            {"NODE_BINARY": "/opt/homebrew/bin/node"},
            attrs={"id": "id_config"},
        ),
    )

    assert "function getMetaForKey_id_config" in html
    assert "if (key.endsWith('_BINARY'))" in html
    assert "Path to binary executable" in html


def test_key_value_widget_prefills_known_config_values_from_query_string():
    html = str(KeyValueWidget().render("config", {}, attrs={"id": "id_config"}))

    assert "new URLSearchParams(window.location.search)" in html
    assert "prefillConfigFromQuery_id_config" in html
    assert "configMeta_id_config[key]" in html
    assert "valueInput.value = value" in html
    assert "params.forEach(function(value, key)" in html
    assert "configMeta_id_config[key]" in html
    assert "consumedConfigKeys.forEach" in html
    assert "window.history.replaceState(null, '', cleanUrl.pathname + cleanUrl.search + cleanUrl.hash)" in html


def test_unconfigured_superuser_banner_uses_browser_assisted_setup_wizard():
    html = render_to_string(
        "core/system_warnings_banner.html",
        {
            "mode": "unconfigured",
            "can_configure": True,
            "canonical_host": "archivebox.example.test:8000",
            "suggested_base_url": "http://archivebox.example.test:8000",
            "machine_admin_url": "/admin/machine/machine/current/change/",
            "public_index": True,
            "public_add_view": False,
            "permissions": "private",
        },
    )

    assert html.count('id="archivebox-setup-wizard"') == 1
    assert 'id="archivebox-system-warning-banner"' not in html
    assert "⚠ base_url not set" not in html
    assert "Setup access to your ArchiveBox Server: <code>archivebox.example.test:8000</code>" in html
    assert 'id="archivebox-setup-base-url"' in html
    assert 'id="archivebox-setup-security-mode"' in html
    assert 'id="archivebox-setup-public-index"' in html
    assert 'id="archivebox-setup-public-add"' in html
    assert 'id="archivebox-setup-permissions"' in html
    assert 'id="archivebox-setup-effective-mode"' in html
    assert 'id="archivebox-setup-browser-url"' in html
    assert 'id="archivebox-setup-configured-url"' in html
    assert 'id="archivebox-setup-url-match"' in html
    assert 'name="archivebox-hosting-location"' in html
    assert 'name="archivebox-dns-mode"' in html
    assert 'name="archivebox-tls-mode"' in html
    assert (
        html.index('name="archivebox-dns-mode" value="localhost"')
        < html.index(
            'name="archivebox-dns-mode" value="single"',
        )
        < html.index('name="archivebox-dns-mode" value="wildcard"')
    )
    assert (
        html.index('name="archivebox-tls-mode" value="localhost"')
        < html.index(
            'name="archivebox-tls-mode" value="none"',
        )
        < html.index('name="archivebox-tls-mode" value="single"')
        < html.index('name="archivebox-tls-mode" value="wildcard"')
    )
    assert 'id="archivebox-setup-later"' not in html
    assert 'id="archivebox-setup-review" disabled' in html
    assert "as BASE_URL below" not in html
    assert "Required:" not in html
    assert "safe-onedomain-nojsreplay" in html
    assert "simplest self-hosted setup" in html
    assert "safe-subdomains-fullreplay" in html
    assert "unsafe-onedomain-noadmin" in html
    assert "danger-onedomain-fullreplay" in html
    assert "Wildcard DNS" in html
    assert "Modern browsers support wildcard <code>*.archivebox.localhost</code> with no DNS or HTTPS setup required." in html
    assert "A archivebox.example.com" in html
    assert "JavaScript still runs during capture" in html
    assert "will not replay JavaScript unless wildcard DNS is used" in html
    assert "Wildcard TLS" in html
    assert "Never enable on-demand TLS or request individual certificates for snapshot subdomains." in html
    assert "Restart ArchiveBox after saving an HTTPS <code>BASE_URL</code> for the first time." in html
    assert "Cloudflare, Nginx Proxy Manager, Caddy, Traefik, Tailscale" in html
    assert "How will HTTPS traffic reach this ArchiveBox server?" in html
    assert "This mode is not allowed unless also using Single-domain DNS." in html
    assert "No TLS, private networks only" in html
    assert "trusted LAN, VPN, or private network" in html
    assert "In-browser WARC viewing will be disabled unless using <code>localhost</code> or HTTPS" in html
    assert "BASE_URL" in html
    assert "SERVER_SECURITY_MODE" in html
    assert "PUBLIC_INDEX" in html
    assert "PUBLIC_ADD_VIEW" in html
    assert "Be careful archiving any secret URLs or private share URLs" in html
    assert "Beware capturing / viewing archives of URLs that contain malicious JS" in html
    assert "PERMISSIONS" in html
    assert "/admin/machine/machine/current/change/" in html
    assert "setup_wizard.css" in html
    assert 'data-status-id="archivebox-setup-hosting-status"' in html
    assert 'aria-controls="archivebox-setup-hosting-options"' in html
    assert 'data-status-id="archivebox-setup-dns-status"' in html
    assert 'aria-controls="archivebox-setup-dns-options"' in html
    assert 'data-status-id="archivebox-setup-tls-status"' in html
    assert 'aria-controls="archivebox-setup-tls-options"' in html
    assert "setup_wizard.js?v=20260726-1" in html


def test_first_admin_setup_suppresses_unconfigured_warning():
    assert system_warnings_banner({"first_admin_setup": True}) == {"mode": ""}


def test_setup_wizard_assets_enforce_selection_and_access_requirements():
    assert "border-color:#15803d; background:#f0fdf4" in SETUP_WIZARD_CSS
    assert "accent-color:#15803d" in SETUP_WIZARD_CSS
    assert "#archivebox-setup-title code { font-size:inherit; line-height:inherit; }" in SETUP_WIZARD_CSS
    assert ".abx-question.is-collapsed .abx-question-options { display:none; }" in SETUP_WIZARD_CSS
    assert ".abx-question.is-collapsed { padding:8px 12px 10px; }" in SETUP_WIZARD_CSS
    assert ".abx-question.is-collapsed .abx-question-status { margin:0; padding:3px 6px 0; background:transparent; }" in SETUP_WIZARD_CSS
    assert ".abx-question legend { box-sizing:border-box; width:100%;" in SETUP_WIZARD_CSS
    assert "flex:0 0 22px" in SETUP_WIZARD_CSS
    assert ".abx-question.is-valid legend { background:#f0fdf4; }" in SETUP_WIZARD_CSS
    assert ".abx-question.is-valid { border-color:#15803d; background:#f0fdf4" in SETUP_WIZARD_CSS
    assert ".abx-question.is-invalid { border-color:#dc2626;" in SETUP_WIZARD_CSS

    assert "updateQuestionDefaults" not in SETUP_WIZARD_JS
    assert "function initializeQuestionSections()" in SETUP_WIZARD_JS
    assert "var isValid = statusText.indexOf('✅') === 0" in SETUP_WIZARD_JS
    assert "var isInvalid = statusText.indexOf('❌') === 0" in SETUP_WIZARD_JS
    assert "if (isValid) setCollapsed(true)" in SETUP_WIZARD_JS
    assert "if (isInvalid) setCollapsed(false)" in SETUP_WIZARD_JS
    assert "toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true')" in SETUP_WIZARD_JS
    assert "toggleIcon.textContent = collapsed ? '▸' : '▾'" in SETUP_WIZARD_JS
    assert "canonicalHost" not in SETUP_WIZARD_JS
    assert "Browser URL matches BASE_URL." in SETUP_WIZARD_JS
    assert "Browser URL matches admin.BASE_URL as expected." in SETUP_WIZARD_JS
    assert "Browser URL does not match BASE_URL" in SETUP_WIZARD_JS
    assert "saved URLs may contain private share tokens or other secrets." in SETUP_WIZARD_JS
    assert "archive intranet URLs" in SETUP_WIZARD_JS
    assert "tlsMode === 'single' && dnsMode !== 'single'" in SETUP_WIZARD_JS
    assert "Single-domain HTTPS is only allowed with Single-domain DNS." in SETUP_WIZARD_JS
    assert "Never enable on-demand TLS or request individual snapshot certificates." in SETUP_WIZARD_JS
    assert "expectedBrowserOrigin: usesSubdomains ? adminOrigin : parsed.origin" in SETUP_WIZARD_JS
    assert "Waiting for a matching browser URL and valid setup options" in SETUP_WIZARD_JS
    assert "Finish the selected DNS, ingress, and TLS setup" in SETUP_WIZARD_JS

    for target in ("adminUrl", "apiUrl", "indexUrl"):
        assert f"probeUrl(preview.{target}" in SETUP_WIZARD_JS
    assert "wildcardHealthUrl" not in SETUP_WIZARD_JS
    assert "results.wildcard" not in SETUP_WIZARD_JS
    assert "var coreReachable = results.admin && results.api && results.index && results.web && results.snapshot;" in SETUP_WIZARD_JS
    assert "probeUrl(webOrigin + '/web/https://example.com'" not in SETUP_WIZARD_JS
    assert "credentials: 'omit'" in SETUP_WIZARD_JS
    assert "function probeUrl(url, generation, requireArchiveBoxHealth)" in SETUP_WIZARD_JS
    assert "mode: requireArchiveBoxHealth ? 'cors' : 'no-cors'" in SETUP_WIZARD_JS
    assert "response.ok && response.headers.get('X-ArchiveBox-Health') === 'OK'" in SETUP_WIZARD_JS
    for target in ("webHealthUrl", "snapshotHealthUrl", "originalHealthUrl"):
        assert f"probeUrl(preview.{target}, generation, true)" in SETUP_WIZARD_JS


def test_health_check_is_identifiable_across_ingress_origins():
    response = HealthCheckView.as_view()(RequestFactory().get("/health/"))

    assert response.status_code == 200
    assert response.content == b"OK"
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Access-Control-Expose-Headers"] == "X-ArchiveBox-Health"
    assert response["X-ArchiveBox-Health"] == "OK"


@pytest.mark.parametrize(
    ("request_host", "secure", "expected_display_host"),
    (
        ("admin.archivebox.localhost:8000", False, "archivebox.localhost:8000"),
        ("127.0.0.1:8000", False, "archivebox.localhost:8000"),
        ("0.0.0.0:8000", False, "archivebox.localhost:8000"),
        ("archivebox.io:80", False, "archivebox.io"),
        ("archivebox.io:443", True, "archivebox.io"),
        ("192.0.2.10:443", True, "192.0.2.10"),
    ),
)
def test_unconfigured_banner_displays_canonical_url_host(request_host, secure, expected_display_host):
    request = RequestFactory().get("/admin/", secure=secure, HTTP_HOST=request_host)
    request.user = AnonymousUser()

    context = get_setup_wizard_context(request, get_config(include_machine=False))

    assert context["display_host"] == expected_display_host


def test_unconfigured_banner_honors_forwarded_https_from_ingress():
    request = RequestFactory().get(
        "/admin/",
        HTTP_HOST="archivebox.example.test",
        HTTP_X_FORWARDED_PROTO="https",
    )
    request.user = AnonymousUser()

    context = get_setup_wizard_context(request, get_config(include_machine=False))

    assert context["suggested_base_url"] == "https://archivebox.example.test"


@pytest.mark.parametrize(
    ("base_url", "request_host"),
    (
        ("", "archivebox.example.test:18443"),
        ("http://archivebox.localhost:8000", "admin.archivebox.localhost:18010"),
    ),
)
def test_admin_cookie_isolation_accepts_first_run_and_external_port_mapping(base_url, request_host):
    config = get_config(include_machine=False).model_copy(
        update={"BASE_URL": base_url, "SERVER_SECURITY_MODE": "auto"},
    )
    request = RequestFactory().get("/admin/login/", HTTP_HOST=request_host)
    request.archivebox_config = config
    response = HttpResponse()
    response.set_cookie(settings.CSRF_COOKIE_NAME, "test-token")

    actual_response = AdminCookieIsolationMiddleware(lambda _request: response)(request)

    assert settings.CSRF_COOKIE_NAME in actual_response.cookies


def test_unconfigured_banner_does_not_show_setup_wizard_to_non_superusers():
    html = render_to_string(
        "core/system_warnings_banner.html",
        {
            "mode": "unconfigured",
            "can_configure": False,
            "suggested_base_url": "http://archivebox.example.test:8000",
        },
    )

    assert 'id="archivebox-setup-wizard"' not in html
    assert html.count('id="archivebox-system-warning-banner"') == 1
    assert "Ask an ArchiveBox superuser to finish server setup" in html


@pytest.mark.parametrize(
    ("context", "expected_text"),
    (
        ({"mode": "low_disk", "free_gb": "0.50"}, "Only <code"),
        ({"mode": "high_memory", "mem_pct": "97.0"}, "Virtual memory at"),
        ({"mode": "high_load", "load_15": "8.0", "load_threshold": 6, "cpu_count": 2}, "15-min loadavg"),
        ({"mode": "unsafe"}, "ArchiveBox single-domain mode"),
    ),
)
def test_system_warning_modes_share_one_banner(context, expected_text):
    html = render_to_string("core/system_warnings_banner.html", context)

    assert html.count('id="archivebox-system-warning-banner"') == 1
    assert expected_text in html


def test_configured_base_url_mismatch_banner_shows_both_origins():
    config = get_config(include_machine=False).model_copy(update={"BASE_URL": "https://archivebox.example.test"})
    request = RequestFactory().get("/admin/", HTTP_HOST="archivebox.internal:8000")
    request.user = AnonymousUser()

    context = get_base_url_mismatch_context(request, config)
    assert context == {
        "mode": "base_url_mismatch",
        "browser_url": "http://archivebox.internal:8000",
        "configured_base_url": "https://archivebox.example.test",
    }
    assert system_warnings_banner({"CONFIG": config, "request": request}) == context

    html = render_to_string("core/system_warnings_banner.html", context)
    assert "base_url mismatch" in html
    assert "Browser URL:" in html
    assert "http://archivebox.internal:8000" in html
    assert "Configured BASE_URL:" in html
    assert "https://archivebox.example.test" in html


def test_configured_base_url_accepts_its_isolated_admin_subdomain():
    config = get_config(include_machine=False).model_copy(
        update={"BASE_URL": "https://archivebox.example.test", "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay"},
    )
    request = RequestFactory().get("/admin/", secure=True, HTTP_HOST="admin.archivebox.example.test")
    request.user = AnonymousUser()

    assert get_base_url_mismatch_context(request, config) is None


def test_configured_onedomain_base_url_warns_on_admin_alias():
    config = get_config(include_machine=False).model_copy(
        update={"BASE_URL": "https://archivebox.example.test", "SERVER_SECURITY_MODE": "safe-onedomain-nojsreplay"},
    )
    request = RequestFactory().get("/admin/", secure=True, HTTP_HOST="admin.archivebox.example.test")
    request.user = AnonymousUser()

    assert get_base_url_mismatch_context(request, config)["mode"] == "base_url_mismatch"


def test_auto_onedomain_mode_is_not_reported_as_unsafe():
    config = get_config(include_machine=False).model_copy(
        update={"BASE_URL": "http://archivebox.example.test", "SERVER_SECURITY_MODE": "auto"},
    )

    assert config.USES_SUBDOMAIN_ROUTING is False
    assert system_warnings_banner({"CONFIG": config})["mode"] != "unsafe"
