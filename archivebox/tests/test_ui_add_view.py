import json
from abx_plugins.plugins.base.testing import install_binary_with_abxpkg
from abx_plugins.plugins.opencode.archivebox.host_cases import (
    test_add_view_hides_agent_link_when_opencode_is_disabled as test_add_view_hides_agent_link_when_opencode_is_disabled,
)


from asgiref.sync import async_to_sync

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse

from archivebox.config.common import ArchiveBoxConfig, get_config
from archivebox.core.models import Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Binary, Machine
from archivebox.personas.models import Persona
from archivebox.services.runner import CrawlRunner
from archivebox.workers.models import RETRY_AT_MAX

pytestmark = pytest.mark.django_db

User = get_user_model()
WEB_HOST = "web.archivebox.localhost:5797"
ADMIN_HOST = "admin.archivebox.localhost:5797"


ADD_FORM_DEFAULTS = {
    "tag": "",
    "depth": "0",
    "max_urls": "0",
    "crawl_max_size": "0",
    "snapshot_max_size": "0",
    "url_filters_allowlist": "",
    "url_filters_denylist": "",
    "notes": "",
    "schedule": "",
    "persona": "Default",
    "permissions": "public",
    "start_paused": "",
    "config": "{}",
}


@pytest.fixture(autouse=True)
def initialized_persona(db):
    # Match init/server startup; rendering /add/ must no longer create DB rows.
    return Persona.get_or_create_default()


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="addviewadmin",
        email="addviewadmin@test.com",
        password="testpassword",
    )


@pytest.fixture
def public_add_enabled():
    return Machine.from_json({"config": {"PUBLIC_ADD_VIEW": True}})


def test_empty_persona_binary_lookup_does_not_query_installed_binaries():
    from archivebox.plugins.discovery import discover_plugin_configs
    from archivebox.plugins.forms import build_required_binary_url_lookup

    plugin_configs = discover_plugin_configs()
    with CaptureQueriesContext(connection) as queries:
        assert build_required_binary_url_lookup(plugin_configs, []) == {}
    assert len(queries) == 0


def test_add_view_batches_binary_links_and_preserves_persona_path_selection(client, admin_user):
    machine = Machine.current()
    wget = install_binary_with_abxpkg("wget", binproviders="env,brew,apt")
    curl = install_binary_with_abxpkg("curl", binproviders="env,brew,apt")
    assert wget.loaded_abspath and curl.loaded_abspath
    wget_path = str(wget.loaded_abspath)
    curl_path = str(curl.loaded_abspath)
    older = Binary.objects.create(machine=machine, name="wget", abspath=wget_path, version="older")
    newest = Binary.objects.create(machine=machine, name="wget", abspath=wget_path, version="newer")
    exact_path = Binary.objects.create(machine=machine, name="custom-fetcher", abspath=curl_path, version="installed")
    empty = Binary.objects.create(machine=machine, name="wget", abspath="", version="")
    personas = {
        "Named": ("WGET", newest),
        "ExactPath": (curl_path, exact_path),
        "Basename": ("/not-installed/wget", newest),
        "Missing": ("missing-downloader", None),
    }
    for name, (value, _binary) in personas.items():
        Persona.objects.create(name=name, config={"WGET_BINARY": value})
    client.force_login(admin_user)
    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("add"), HTTP_HOST=ADMIN_HOST)
    assert response.status_code == 200
    configs = json.loads(response.context["persona_config_map_json"])
    for name, (_value, binary) in personas.items():
        url = configs[name]["binary_urls"]["WGET_BINARY"]
        if binary:
            assert binary.admin_change_url in url
            assert empty.admin_change_url not in url
        else:
            assert url == "/admin/environment/binaries/missing-downloader/"
    binary_queries = [query for query in queries if 'FROM "machine_binary"' in query["sql"]]
    # One shared persona batch plus the form's own binary-link batch.
    assert len(binary_queries) == 2
    newest.abspath = ""
    newest.save(update_fields=["abspath"])
    updated = client.get(reverse("add"), HTTP_HOST=ADMIN_HOST)
    assert updated.status_code == 200
    updated_configs = json.loads(updated.context["persona_config_map_json"])
    assert older.admin_change_url in updated_configs["Named"]["binary_urls"]["WGET_BINARY"]
    assert exact_path.admin_change_url in updated_configs["ExactPath"]["binary_urls"]["WGET_BINARY"]


def test_add_view_renders_tag_editor_and_url_filter_fields(client, admin_user, public_add_enabled):
    response = client.get(reverse("add"), HTTP_HOST=WEB_HOST)
    form = response.context["form"]

    assert response.status_code == 200
    assert response.context["can_override_crawl_config"] is False
    assert form.plugin_groups == []
    placeholder = form.fields["url"].widget.attrs["placeholder"]
    assert isinstance(placeholder, str)
    assert placeholder.startswith("Enter URL(s) to archive.")
    assert "https://example.com\n\nhttps://news.ycombinator.com" in placeholder
    assert {
        "url",
        "tag",
        "url_filters",
        "persona",
        "permissions",
        "depth",
        "max_urls",
        "crawl_max_size",
        "crawl_timeout",
        "timeout",
        "snapshot_max_size",
        "delete_after",
        "crawl_max_concurrent_snapshots",
        "start_paused",
        "notes",
    }.issubset(form.fields)
    assert b'name="url_filters_only_new"' in response.content
    assert b"Only new URLs" in response.content
    assert b"skip URLs you&#x27;ve previously saved" in response.content or b"skip URLs you've previously saved" in response.content


def test_add_view_admin_renders_plugin_settings(client, admin_user):
    client.force_login(admin_user)

    response = client.get(reverse("add"), HTTP_HOST=ADMIN_HOST)
    form = response.context["form"]

    assert response.status_code == 200
    assert response.context["can_override_crawl_config"] is True
    assert form.plugin_groups
    assert any(card["config_fields"] for group in form.plugin_groups for card in group["plugins"])
    assert b"Index only dry run" not in response.content
    assert b"Start paused" in response.content
    assert "Source ↗</a>" in response.content.decode()
    assert "Documentation ↗</a>" in response.content.decode()
    assert b"https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/" in response.content
    assert b"https://plugins.archivebox.io/#" in response.content
    assert not any(
        field["key"].endswith("_BINARY") for group in form.plugin_groups for card in group["plugins"] for field in card["config_fields"]
    )
    assert not any(
        field["key"] == f"{card['name'].upper()}_ENABLED"
        for group in form.plugin_groups
        for card in group["plugins"]
        for field in card["config_fields"]
    )
    exposed_config_keys = {field["key"] for group in form.plugin_groups for card in group["plugins"] for field in card["config_fields"]}
    assert not {key for key in exposed_config_keys if ArchiveBoxConfig.scope_for_key(key) == "crawl_execution"}
    assert (
        not {
            "ARCHIVE_DIR",
            "USERS_DIR",
            "PERSONAS_DIR",
            "CUSTOM_TEMPLATES_DIR",
        }
        & exposed_config_keys
    )
    assert b"plugin_config__chrome__CHROME_BINARY" not in response.content
    assert b"plugin_config__wget__WGET_ENABLED" not in response.content


def test_add_view_staff_user_cannot_override_raw_or_plugin_config(client):
    staff_user = User.objects.create_user(
        username="addviewstaff",
        email="addviewstaff@test.com",
        password="testpassword",
        is_staff=True,
        is_superuser=False,
    )
    client.force_login(staff_user)

    response = client.get(reverse("add"), HTTP_HOST=ADMIN_HOST)
    assert response.status_code == 200
    assert response.context["can_override_crawl_config"] is False
    assert response.context["form"].plugin_groups == []
    assert b"plugin_config__wget__WGET_TIMEOUT" not in response.content
    assert b"Custom config overrides" not in response.content

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": "https://example.com/staff-config",
            "crawl_timeout": "0",
            "timeout": "60",
            "delete_after": "0",
            "crawl_max_concurrent_snapshots": "1",
            "schedule": "daily",
            "start_paused": "on",
            "main_plugins": ["wget"],
            "plugin_config__wget__WGET_TIMEOUT": "77",
            "config": '{"WGET_TIMEOUT": 77, "YTDLP_ARGS_EXTRA": ["--exec", "touch /tmp/owned"]}',
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302
    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.created_by == staff_user
    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.schedule is None
    assert crawl.config.get("PLUGINS", "") == ""
    assert crawl.config.get("WGET_TIMEOUT") != 77
    assert crawl.config.get("YTDLP_ARGS_EXTRA") != ["--exec", "touch /tmp/owned"]


def test_add_view_embeds_selected_persona_config_for_ui_hydration(client, admin_user):
    client.force_login(admin_user)
    default_persona = Persona.get_or_create_default()
    default_persona.config = {
        "COOKIES_FILE": "/tmp/archivebox-default-cookies.txt",
        "USER_AGENT": "ArchiveBox Default Persona UA",
    }
    default_persona.save(update_fields=["config"])
    Persona.objects.create(
        name="Private",
        created_by=admin_user,
        config={"WGET_TIMEOUT": 88, "CHROME_HEADLESS": False, "COOKIES_FILE": "/tmp/archivebox-private-cookies.txt"},
    )

    response = client.get(reverse("add"), HTTP_HOST=ADMIN_HOST)
    assert response.status_code == 200
    persona_config_map = json.loads(response.context["persona_config_map_json"])
    assert persona_config_map["Default"]["effective_config"]["YTDLP_COOKIES_FILE"] == "/tmp/archivebox-default-cookies.txt"
    assert persona_config_map["Private"]["effective_config"]["YTDLP_COOKIES_FILE"] == "/tmp/archivebox-private-cookies.txt"


def test_add_view_public_only_lists_public_personas(client, admin_user, public_add_enabled):
    secret_value = "SHOULD_NOT_LEAK_PUBLIC_PERSONA_SECRET"
    default_persona = Persona.get_or_create_default()
    default_persona.config = {"PERMISSIONS": "public", "NODE_BINARY": "/secret/node", "TWOCAPTCHA_API_KEY": secret_value}
    default_persona.save(update_fields=["config"])
    Persona.objects.create(name="Unlisted", created_by=admin_user, config={"PERMISSIONS": "unlisted"})
    Persona.objects.create(name="Private", created_by=admin_user, config={"PERMISSIONS": "private"})

    response = client.get(reverse("add"), HTTP_HOST=WEB_HOST)
    form = response.context["form"]
    persona_config_map = json.loads(response.context["persona_config_map_json"])

    assert response.status_code == 200
    assert set(form.fields["persona"].queryset.values_list("name", flat=True)) == {"Default"}
    assert secret_value.encode() not in response.content
    assert set(persona_config_map.keys()) == {"Default"}
    assert {"NODE_BINARY", "TWOCAPTCHA_API_KEY"}.isdisjoint(persona_config_map["Default"]["effective_config"])


def test_persona_config_grid_allows_binary_fields(client, admin_user):
    client.force_login(admin_user)
    persona = Persona.objects.create(name="Binary Persona", created_by=admin_user)

    response = client.get(
        reverse("admin:personas_persona_change", args=[persona.pk]),
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert b"plugin_config__chrome__CHROME_BINARY" in response.content
    assert b"plugin_config__wget__WGET_ENABLED" in response.content


def test_add_view_hides_search_backend_plugins(client, public_add_enabled):
    public_add_enabled.config["SEARCH_BACKEND_ENGINE"] = "sqlite"
    public_add_enabled.save(update_fields=["config"])

    response = client.get(reverse("add"), HTTP_HOST=WEB_HOST)
    form = response.context["form"]

    assert response.status_code == 200
    assert form.plugin_groups == []


def test_add_view_creates_crawl_with_tag_and_url_filter_overrides(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": "https://example.com\nhttps://cdn.example.com/asset.js",
            "tag": "alpha,beta",
            "depth": "1",
            "max_urls": "3",
            "crawl_max_size": "45mb",
            "crawl_timeout": "120",
            "timeout": "1.5m",
            "snapshot_max_size": "5mb",
            "delete_after": "2h",
            "crawl_max_concurrent_snapshots": "5",
            "url_filters_allowlist": "example.com\n*.example.com",
            "url_filters_denylist": "cdn.example.com",
            "url_filters_only_new": "1",
            "notes": "Created from /add/",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()

    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.tags_str == "alpha,beta"
    assert crawl.notes == "Created from /add/"
    assert crawl.config["CRAWL_MAX_URLS"] == 3
    assert crawl.config["CRAWL_MAX_SIZE"] == 45 * 1024 * 1024
    assert crawl.config["CRAWL_TIMEOUT"] == 120
    assert crawl.config["TIMEOUT"] == 90
    assert crawl.config["SNAPSHOT_MAX_SIZE"] == 5 * 1024 * 1024
    assert crawl.config["DELETE_AFTER"] == "2h"
    assert crawl.delete_at is not None
    assert crawl.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 5
    assert crawl.config["URL_ALLOWLIST"] == "example.com\n*.example.com"
    assert crawl.config["URL_DENYLIST"] == "cdn.example.com"
    assert crawl.config["ONLY_NEW"] is True


@pytest.mark.parametrize("concurrency", [None, "", "0", "3", "-1"])
def test_add_view_preserves_automatic_concurrency(client, public_add_enabled, concurrency):
    data = {**ADD_FORM_DEFAULTS, "url": "https://example.com/automatic-concurrency"}
    if concurrency is not None:
        data["crawl_max_concurrent_snapshots"] = concurrency

    response = client.post(reverse("add"), data=data, HTTP_HOST=WEB_HOST)

    if concurrency == "-1":
        assert response.status_code == 200
        error = response.context["form"].errors.as_data()["crawl_max_concurrent_snapshots"][0]
        assert error.code == "min_value"
        assert not Crawl.objects.exists()
        return

    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()
    crawl = Crawl.objects.get(urls=data["url"])
    assert get_config(crawl=crawl).CRAWL_MAX_CONCURRENT_SNAPSHOTS == (3 if concurrency == "3" else 0)


@pytest.mark.django_db(transaction=True)
def test_add_view_persona_switch_restores_automatic_concurrency(public_add_enabled, live_server, browser_runtime):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    port = urlsplit(live_server.url).port
    public_add_enabled.config["BASE_URL"] = f"http://archivebox.localhost:{port}"
    public_add_enabled.save(update_fields=["config"])
    Persona.objects.create(name="Limited", config={"PERMISSIONS": "public", "CRAWL_MAX_CONCURRENT_SNAPSHOTS": 3})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page()
        page.goto(f"http://web.archivebox.localhost:{port}/add/")
        concurrency = page.locator('input[name="crawl_max_concurrent_snapshots"]')
        expect(concurrency).to_have_value("0")
        page.locator('select[name="persona"]').select_option("Limited")
        expect(concurrency).to_have_value("3")
        page.locator('select[name="persona"]').select_option("Default")
        expect(concurrency).to_have_value("0")
        expect(concurrency).to_have_attribute("min", "0")
        assert concurrency.evaluate("input => input.checkValidity()")
        browser.close()


@pytest.mark.django_db(transaction=True)
def test_add_view_linked_persona_config_wins_over_saved_persona(public_add_enabled, live_server, browser_runtime, admin_user):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    port = urlsplit(live_server.url).port
    public_add_enabled.config["BASE_URL"] = f"http://archivebox.localhost:{port}"
    public_add_enabled.save(update_fields=["config"])
    Persona.objects.create(name="Saved", config={"PERMISSIONS": "public", "CRAWL_MAX_CONCURRENT_SNAPSHOTS": 3, "TIMEOUT": 23})
    Persona.objects.create(name="Linked", config={"PERMISSIONS": "public", "CRAWL_MAX_CONCURRENT_SNAPSHOTS": 5, "TIMEOUT": 61})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page()
        base = f"http://admin.archivebox.localhost:{port}/add/"
        page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/add/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.goto(base)
        page.locator('select[name="persona"]').select_option("Saved")
        expect(page.locator('input[name="timeout"]')).to_have_value("23")
        assert page.evaluate("JSON.parse(localStorage.getItem('archivebox_add_form_state')).persona") == "Saved"
        page.goto(base + "?persona=Linked&crawl_max_concurrent_snapshots=7")
        expect(page.locator('select[name="persona"]')).to_have_value("Linked")
        expect(page.locator('input[name="timeout"]')).to_have_value("61")
        expect(page.locator('input[name="crawl_max_concurrent_snapshots"]')).to_have_value("7")
        assert json.loads(page.locator('input[name="config"]').input_value())["TIMEOUT"] == 61
        browser.close()


def _csrf_test_add_data(url: str) -> dict[str, str]:
    return {
        **ADD_FORM_DEFAULTS,
        "url": url,
        "crawl_timeout": "0",
        "timeout": "",
        "delete_after": "0",
        "crawl_max_concurrent_snapshots": "1",
    }


def test_add_view_rejects_authenticated_post_without_csrf_token(admin_user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)

    response = client.post(reverse("add"), data=_csrf_test_add_data("https://example.com/csrf"), HTTP_HOST=ADMIN_HOST)

    assert response.status_code == 403
    assert not Crawl.objects.filter(urls__contains="example.com/csrf").exists()


def test_public_add_view_allows_anonymous_post_without_csrf_cookie(public_add_enabled):
    client = Client(enforce_csrf_checks=True)

    response = client.post(reverse("add"), data=_csrf_test_add_data("https://example.com/public-add"), HTTP_HOST=WEB_HOST)

    assert response.status_code == 302
    assert Crawl.objects.filter(urls__contains="example.com/public-add").exists()


def test_add_view_sanitizes_crawl_notes_before_safe_update(client, admin_user):
    client.force_login(admin_user)
    malicious_notes = "</script><script id=add-notes-xss>window.__archivebox_add_notes_xss__=1</script>"

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": "https://example.com/notes-xss",
            "max_urls": "1",
            "crawl_timeout": "0",
            "timeout": "",
            "delete_after": "0",
            "crawl_max_concurrent_snapshots": "1",
            "notes": malicious_notes,
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()
    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.notes == "window.__archivebox_add_notes_xss__=1"
    assert "<script" not in crawl.notes
    assert "</script>" not in crawl.notes


def test_add_view_unchecked_only_new_sets_crawl_override(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": "https://example.com/rearchive",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()
    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.config["ONLY_NEW"] is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("authenticated", [False, True])
def test_add_view_local_path_tokens_never_import_file_contents(client, admin_user, public_add_enabled, tmp_path, authenticated):
    # #1918 mixed a genuine URL with local paths. A URL-only assertion misses
    # disclosure in saved source text, so inspect both parser outputs and files.
    secret = tmp_path / "private-source.txt"
    secret_content = "local-file-canary-1918\nhttps://example.com/private-canary\n"
    secret.write_text(secret_content)
    submitted = f"https://example.com/safe\n{secret}\n{secret.as_uri()}\n{secret.name}\nC:\\private.txt\n\\\\server\\share\\private.txt"
    if authenticated:
        client.force_login(admin_user)
    response = client.post(
        reverse("add"),
        data={**ADD_FORM_DEFAULTS, "url": submitted},
        HTTP_HOST=ADMIN_HOST if authenticated else WEB_HOST,
    )
    assert response.status_code == 302, response.content
    crawl = Crawl.objects.latest("created_at")
    assert crawl.urls == submitted
    runner = CrawlRunner(crawl, selected_plugins=["parse_txt_urls"], show_progress=False)
    runner.load_run_state()
    assert set(crawl.snapshot_set.values_list("url", flat=True)) == {"https://example.com/safe"}
    source = crawl.output_dir / "input" / "staticfile" / "stdin.txt"
    assert source.read_text() == submitted
    for saved in crawl.output_dir.rglob("*"):
        if saved.is_file():
            assert b"local-file-canary-1918" not in saved.read_bytes(), saved
    assert secret.read_text() == secret_content


# The runner prepares payloads on a separate DB connection, as in the real server.
@pytest.mark.django_db(transaction=True)
def test_add_view_selected_persona_wins_over_stale_config_override(client, admin_user):
    client.force_login(admin_user)
    private_persona = Persona.objects.create(name="Private", created_by=admin_user)
    private_persona.ensure_dirs()
    private_cookies_file = private_persona.path / "cookies.txt"
    private_cookies_file.write_text("# Private cookies\n", encoding="utf-8")

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": "https://example.com/private",
            "url_filters_only_new": "1",
            "persona": "Private",
            "config": '{"DEFAULT_PERSONA": "Default"}',
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()

    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.persona_id == private_persona.id
    assert "ACTIVE_PERSONA" not in crawl.config
    assert crawl.resolve_persona() == private_persona
    runner = CrawlRunner(crawl, selected_plugins=["title"], show_progress=False)
    snapshot_ids = runner.load_run_state()
    snapshot = crawl.snapshot_set.get(id=snapshot_ids[0], url="https://example.com/private")
    runtime_config = async_to_sync(runner.load_snapshot_payload)(str(snapshot.id))["config"]
    assert runtime_config["ACTIVE_PERSONA"] == "Private"
    assert runtime_config["COOKIES_FILE"] == str(private_cookies_file)


def test_add_view_applies_plugin_config_overrides(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": "https://example.com/plugin-config",
            "url_filters_only_new": "1",
            "main_plugins": ["wget"],
            "plugin_config__wget__WGET_ENABLED": "false",
            "plugin_config__wget__WGET_TIMEOUT": "77",
            "plugin_config__wget__WGET_WARC_ENABLED": "false",
            "plugin_config__chrome__CHROME_BINARY": "/tmp/malicious-chrome",
            "config": '{"NODE_BINARY": "/tmp/malicious-node", "WGET_ENABLED": false}',
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302

    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.config["PLUGINS"] == "wget"
    assert crawl.config["WGET_TIMEOUT"] == 77
    assert crawl.config["WGET_WARC_ENABLED"] is False
    assert "WGET_ENABLED" not in crawl.config
    assert "CHROME_BINARY" not in crawl.config
    assert "NODE_BINARY" not in crawl.config


@pytest.mark.parametrize("empty_filters", [False, True])
def test_add_view_public_submission_ignores_plugin_and_custom_config(client, admin_user, public_add_enabled, empty_filters):
    public_add_enabled.config.update({"URL_ALLOWLIST": "example.com", "URL_DENYLIST": "example.com/global-blocked"})
    public_add_enabled.save(update_fields=["config"])

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": "https://example.com/public-safe",
            "max_urls": "10",
            "crawl_max_size": "45mb",
            "crawl_timeout": "120",
            "timeout": "1.5m",
            "snapshot_max_size": "5mb",
            "delete_after": "2h",
            "crawl_max_concurrent_snapshots": "2",
            "url_filters_allowlist": "" if empty_filters else "example.com",
            "url_filters_denylist": "" if empty_filters else "cdn.example.com",
            "url_filters_only_new": "1",
            "notes": "public add",
            "schedule": "daily",
            "start_paused": "on",
            "main_plugins": ["wget"],
            "plugin_config__twocaptcha__TWOCAPTCHA_API_KEY": "posted-token",
            "plugin_config__wget__WGET_TIMEOUT": "77",
            "config": '{"NODE_BINARY": "/tmp/node", "TWOCAPTCHA_API_KEY": "posted-token", "URL_ALLOWLIST": "bad.example.com"}',
        },
        HTTP_HOST=WEB_HOST,
    )

    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()
    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.config["CRAWL_MAX_URLS"] == 10
    assert crawl.config["CRAWL_MAX_SIZE"] == 45 * 1024 * 1024
    assert crawl.config["CRAWL_TIMEOUT"] == 120
    assert crawl.config["TIMEOUT"] == 90
    assert crawl.config["SNAPSHOT_MAX_SIZE"] == 5 * 1024 * 1024
    assert crawl.config["DELETE_AFTER"] == "2h"
    assert crawl.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 2
    assert crawl.config["URL_ALLOWLIST"] == "example.com"
    assert crawl.config["URL_DENYLIST"] == ("example.com/global-blocked" if empty_filters else "cdn.example.com")
    assert not crawl.url_passes_filters("https://other.example/public-safe")
    assert not crawl.url_passes_filters("https://example.com/global-blocked" if empty_filters else "https://cdn.example.com/")
    assert crawl.config.get("PLUGINS", "") == ""
    assert crawl.config.get("WGET_TIMEOUT") != 77
    assert crawl.config.get("NODE_BINARY") != "/tmp/node"
    assert crawl.config.get("TWOCAPTCHA_API_KEY") != "posted-token"
    assert crawl.config.get("INDEX_ONLY") is not True
    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.schedule is None

    if empty_filters:
        client.force_login(admin_user)
        response = client.post(
            reverse("add"),
            data={**ADD_FORM_DEFAULTS, "url": "https://other.example/admin-cleared", "crawl_max_concurrent_snapshots": "2"},
            HTTP_HOST=ADMIN_HOST,
        )
        assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()
        cleared = Crawl.objects.order_by("-created_at").first()
        assert cleared.config["URL_ALLOWLIST"] == ""
        assert cleared.config["URL_DENYLIST"] == ""
        assert cleared.url_passes_filters("https://other.example/admin-cleared")


def test_add_view_creates_scheduled_crawl_in_inline_created_folder(client, admin_user):
    from archivebox.core.models import Folder

    client.force_login(admin_user)
    parent = Folder.objects.create(name="News")
    response = client.post(
        reverse("admin:core_folder_save"),
        {"name": "Daily", "parent": parent.pk},
        HTTP_HOST=ADMIN_HOST,
    )
    assert response.status_code == 200
    folder = Folder.objects.get(pk=response.json()["id"])
    response = client.get(reverse("add"), {"folder": folder.pk}, HTTP_HOST=ADMIN_HOST)
    assert response.status_code == 200
    assert response.context["form"]["folder"].value() == str(folder.pk)
    assert b"News / Daily" in response.content
    assert b'id="folder-dialog"' in response.content
    response = client.post(
        reverse("add"),
        {**ADD_FORM_DEFAULTS, "url": "https://news.ycombinator.com/newest", "folder": folder.pk, "schedule": "daily"},
        HTTP_HOST=ADMIN_HOST,
    )
    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()
    crawl = Crawl.objects.get(folder=folder)
    assert crawl.schedule.template_id == crawl.pk
    assert crawl.create_snapshots_from_urls()[0].folder_id == folder.pk
    recurring = crawl.schedule.enqueue()
    assert recurring.folder_id == folder.pk
    assert recurring.schedule_id == crawl.schedule_id


def test_add_view_rejects_missing_folder_before_creating_crawl(client, admin_user):
    client.force_login(admin_user)
    response = client.post(
        reverse("add"),
        {**ADD_FORM_DEFAULTS, "url": "https://example.com/missing-folder", "folder": 999999},
        HTTP_HOST=ADMIN_HOST,
    )
    assert response.status_code == 200
    assert "folder" in response.context["form"].errors
    assert not Crawl.objects.exists()


def test_public_add_does_not_offer_or_accept_private_folder_assignment(client, admin_user, public_add_enabled):
    from archivebox.core.models import Folder

    folder = Folder.objects.create(name="Private folder name")
    response = client.get(reverse("add"), HTTP_HOST=WEB_HOST)
    assert response.status_code == 200
    assert b'"id_folder"' not in response.content and folder.name.encode() not in response.content
    response = client.post(
        reverse("add"),
        {**ADD_FORM_DEFAULTS, "url": "https://example.com/public-folder", "folder": folder.pk},
        HTTP_HOST=WEB_HOST,
    )
    assert response.status_code == 302
    assert Crawl.objects.get().folder_id is None


def test_add_view_queues_crawl_for_background_runner(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": "https://example.com",
            "url_filters_only_new": "1",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302
    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is not None
    assert crawl.urls == "https://example.com"
    assert crawl.snapshot_set.count() == 0


def test_add_view_start_paused_creates_paused_crawl_without_snapshots(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": "https://example.com/paused",
            "depth": "1",
            "url_filters_only_new": "1",
            "start_paused": "on",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()
    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.status == Crawl.StatusChoices.PAUSED
    assert crawl.retry_at == RETRY_AT_MAX
    assert crawl.urls == "https://example.com/paused"
    assert crawl.snapshot_set.count() == 0
    assert crawl.config.get("INDEX_ONLY") is not True


def test_add_view_extracts_urls_from_mixed_text_input(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": (
                "https://sweeting.me,https://google.com\n"
                "Notes: [ArchiveBox](https://github.com/ArchiveBox/ArchiveBox), https://news.ycombinator.com\n"
                "[Wiki](https://en.wikipedia.org/wiki/Classification_(machine_learning))\n"
                '{"items":["https://example.com/three"]}\n'
                "csv,https://example.com/four"
            ),
            "url_filters_only_new": "1",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302

    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    expected_input = (
        "https://sweeting.me,https://google.com\n"
        "Notes: [ArchiveBox](https://github.com/ArchiveBox/ArchiveBox), https://news.ycombinator.com\n"
        "[Wiki](https://en.wikipedia.org/wiki/Classification_(machine_learning))\n"
        '{"items":["https://example.com/three"]}\n'
        "csv,https://example.com/four"
    )
    assert crawl.urls == expected_input
    assert crawl.snapshot_set.count() == 0


def test_add_view_trims_trailing_punctuation_from_markdown_urls(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": ("Docs: https://github.com/ArchiveBox/ArchiveBox.\nIssue: https://github.com/abc?abc#234234?."),
            "url_filters_only_new": "1",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302

    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    expected_input = "Docs: https://github.com/ArchiveBox/ArchiveBox.\nIssue: https://github.com/abc?abc#234234?."
    assert crawl.urls == expected_input
    assert crawl.snapshot_set.count() == 0


def test_add_view_exposes_api_token_for_tag_widget_autocomplete(client, admin_user):
    client.force_login(admin_user)

    response = client.get(reverse("add"), HTTP_HOST=ADMIN_HOST)

    assert response.status_code == 200
    assert b"window.ARCHIVEBOX_API_KEY" in response.content


def _create_tagged_snapshot(user, *, permissions="public"):
    crawl = Crawl.objects.create(urls="https://example.com", created_by=user, config={"PERMISSIONS": permissions})
    snapshot = Snapshot.from_json({"url": "https://example.com", "tags": "archive"}, overrides={"crawl": crawl})
    assert snapshot is not None
    return snapshot


def test_tags_autocomplete_requires_auth_when_public_index_disabled(client, admin_user):
    Machine.from_json({"config": {"PUBLIC_INDEX": False}})
    _create_tagged_snapshot(admin_user)

    response = client.get(
        reverse("api-1:tags_autocomplete"),
        {"q": "a"},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 401


def test_tags_autocomplete_lists_only_public_snapshot_tags(client, admin_user):
    Machine.from_json({"config": {"PUBLIC_INDEX": True}})
    _create_tagged_snapshot(admin_user)
    _create_tagged_snapshot(admin_user, permissions="unlisted")
    Tag.objects.create(name="private-empty")

    response = client.get(
        reverse("api-1:tags_autocomplete"),
        {"q": "a"},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert response.json()["tags"][0]["name"] == "archive"


def test_tags_autocomplete_allows_authenticated_user_when_public_index_disabled(client, admin_user):
    Machine.from_json({"config": {"PUBLIC_INDEX": False}})
    Tag.objects.create(name="archive")
    client.force_login(admin_user)

    response = client.get(
        reverse("api-1:tags_autocomplete"),
        {"q": "a"},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert response.json()["tags"][0]["name"] == "archive"


@pytest.mark.parametrize("page", ["add", "persona_change"])
def test_plugin_grid_includes_settings_for_its_page_and_timestamps_last(admin_client, admin_user, page):
    from archivebox.plugins.discovery import get_plugin_catalog
    from archivebox.config.common import ArchiveBoxConfig, config_field_metadata, find_config_section
    from archivebox.config import CONSTANTS_CONFIG

    if page == "add":
        url = reverse("add")
    else:
        persona = Persona.objects.create(name="PluginGridPersona", created_by=admin_user)
        url = reverse("admin:personas_persona_change", args=[persona.pk])
    response = admin_client.get(url, HTTP_HOST=ADMIN_HOST)
    assert response.status_code == 200
    form = response.context["form"] if page == "add" else response.context["adminform"].form
    names = [plugin["name"] for group in form.plugin_groups for plugin in group["plugins"]]
    expected = {plugin.name for plugin in get_plugin_catalog().values() if not plugin.config.hidden}
    importer_names = {plugin.name for plugin in get_plugin_catalog().values() if plugin.config.category == "importers"}
    if page == "add":
        expected -= importer_names
        assert not set(names) & importer_names
        assert b'data-plugin-name="importer_rss"' not in response.content
    else:
        assert importer_names <= set(names)
        derived = ArchiveBoxConfig.runtime_derived_config_keys() | set(ArchiveBoxConfig.computed_config_keys)
        expected |= {
            plugin.name
            for plugin in get_plugin_catalog().values()
            if plugin.config.hidden
            and any(
                key not in CONSTANTS_CONFIG
                and key not in derived
                and ArchiveBoxConfig.scope_for_key(key) in {"crawl_frozen", "crawl_execution"}
                for key in plugin.manifest.get("properties", {})
            )
        }
        expected |= {
            find_config_section(key).lower()
            for key, metadata in config_field_metadata(include_execution=True).items()
            if metadata["plugin"] == "archivebox"
            and key.isupper()
            and key not in CONSTANTS_CONFIG
            and key not in derived
            and key not in {"SECRET_KEY", "PERMISSIONS"}
            and metadata["scope"] in {"crawl_frozen", "crawl_execution"}
        }
    assert set(names) == expected
    assert len(names) == len(expected)
    for name in expected:
        assert f'data-plugin-name="{name}"'.encode() in response.content
    # The same schema drives each visible card, including newly installed plugins.
    # Check every plugin's category and rendered controls, not a fixed allowlist.
    catalog = get_plugin_catalog()
    for group in form.plugin_groups:
        for card in group["plugins"]:
            if card.get("is_core"):
                assert group["field_name"] == "system"
            elif catalog[card["name"]].config.hidden:
                assert group["field_name"] == "shared_settings"
            else:
                assert group["field_name"] == f"{catalog[card['name']].config.category}_plugins"
            for field in card["config_fields"]:
                assert f'name="{field["input_name"]}"'.encode() in response.content
    postprocessing = next(group for group in form.plugin_groups if group["field_name"] == "postprocessing_plugins")
    assert postprocessing["plugins"][-1]["name"] == "opentimestamps"
    assert b'name="plugin_config__opentimestamps__OPENTIMESTAMPS_TIMEOUT"' in response.content
    if page == "add":
        assert "opentimestamps" in dict(form.fields["postprocessing_plugins"].choices)
    else:
        assert b'name="plugin_config__opentimestamps__OPENTIMESTAMPS_ENABLED"' in response.content
