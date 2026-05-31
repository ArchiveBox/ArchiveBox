import json
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from archivebox.config.common import get_config
from archivebox.core.models import Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.workers.models import RETRY_AT_MAX


pytestmark = pytest.mark.django_db

User = get_user_model()
WEB_HOST = "web.archivebox.localhost:8000"
ADMIN_HOST = "admin.archivebox.localhost:8000"


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="addviewadmin",
        email="addviewadmin@test.com",
        password="testpassword",
    )


def test_add_view_renders_tag_editor_and_url_filter_fields(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")

    response = client.get(reverse("add"), HTTP_HOST=WEB_HOST)
    form = response.context["form"]

    assert response.status_code == 200
    assert response.context["can_override_crawl_config"] is False
    assert form.plugin_groups == []
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


def test_add_view_admin_renders_plugin_config_grid(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    client.force_login(admin_user)

    response = client.get(reverse("add"), HTTP_HOST=ADMIN_HOST)
    form = response.context["form"]

    assert response.status_code == 200
    assert response.context["can_override_crawl_config"] is True
    assert form.plugin_groups
    assert any(card["config_fields"] for group in form.plugin_groups for card in group["plugins"])
    assert b"Index only dry run" not in response.content
    assert b"Start paused" in response.content
    assert b">Source</a>" in response.content
    assert b">Docs</a>" in response.content
    assert b"https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/" in response.content
    assert b"https://archivebox.github.io/abx-plugins/#" in response.content
    personas_dir_fields = [
        field
        for group in form.plugin_groups
        for card in group["plugins"]
        for field in card["config_fields"]
        if field["key"] == "PERSONAS_DIR"
    ]
    assert personas_dir_fields
    assert {field["value"] for field in personas_dir_fields} == {str(get_config().PERSONAS_DIR)}


def test_add_view_embeds_selected_persona_config_for_ui_hydration(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
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


def test_add_view_public_only_lists_public_personas(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
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


def test_add_view_hides_search_backend_plugins(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    monkeypatch.setenv("SEARCH_BACKEND_ENGINE", "sqlite")

    response = client.get(reverse("add"), HTTP_HOST=WEB_HOST)
    form = response.context["form"]

    assert response.status_code == 200
    assert form.plugin_groups == []


def test_add_view_creates_crawl_with_tag_and_url_filter_overrides(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
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
            "schedule": "",
            "persona": "Default",
            "permissions": "public",
            "start_paused": "",
            "config": "{}",
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


def test_add_view_unchecked_only_new_sets_crawl_override(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            "url": "https://example.com/rearchive",
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
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()
    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.config["ONLY_NEW"] is False


def test_add_view_selected_persona_wins_over_stale_config_override(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    client.force_login(admin_user)
    private_persona = Persona.objects.create(name="Private", created_by=admin_user)
    private_persona.ensure_dirs()
    private_cookies_file = private_persona.path / "cookies.txt"
    private_cookies_file.write_text("# Private cookies\n", encoding="utf-8")

    response = client.post(
        reverse("add"),
        data={
            "url": "https://example.com/private",
            "tag": "",
            "depth": "0",
            "max_urls": "0",
            "crawl_max_size": "0",
            "snapshot_max_size": "0",
            "url_filters_allowlist": "",
            "url_filters_denylist": "",
            "url_filters_only_new": "1",
            "notes": "",
            "schedule": "",
            "persona": "Private",
            "permissions": "public",
            "start_paused": "",
            "config": '{"DEFAULT_PERSONA": "Default"}',
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()

    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.persona_id == private_persona.id
    assert crawl.config["ACTIVE_PERSONA"] == "Private"
    assert crawl.resolve_persona() == private_persona
    runtime_config = get_config(crawl=crawl)
    assert runtime_config.ACTIVE_PERSONA == "Private"
    assert runtime_config.COOKIES_FILE == private_cookies_file


def test_add_view_applies_plugin_config_overrides(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            "url": "https://example.com/plugin-config",
            "tag": "",
            "depth": "0",
            "max_urls": "0",
            "crawl_max_size": "0",
            "snapshot_max_size": "0",
            "url_filters_allowlist": "",
            "url_filters_denylist": "",
            "url_filters_only_new": "1",
            "notes": "",
            "schedule": "",
            "persona": "Default",
            "permissions": "public",
            "start_paused": "",
            "main_plugins": ["wget"],
            "plugin_config__wget__WGET_TIMEOUT": "77",
            "plugin_config__wget__WGET_WARC_ENABLED": "false",
            "config": "{}",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302

    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.config["PLUGINS"] == "wget"
    assert crawl.config["WGET_TIMEOUT"] == 77
    assert crawl.config["WGET_WARC_ENABLED"] is False


def test_add_view_public_submission_ignores_plugin_and_custom_config(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")

    response = client.post(
        reverse("add"),
        data={
            "url": "https://example.com/public-safe",
            "tag": "",
            "depth": "0",
            "max_urls": "10",
            "crawl_max_size": "45mb",
            "crawl_timeout": "120",
            "timeout": "1.5m",
            "snapshot_max_size": "5mb",
            "delete_after": "2h",
            "crawl_max_concurrent_snapshots": "2",
            "url_filters_allowlist": "example.com",
            "url_filters_denylist": "cdn.example.com",
            "url_filters_only_new": "1",
            "notes": "public add",
            "schedule": "daily",
            "persona": "Default",
            "permissions": "public",
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
    assert crawl.config["URL_DENYLIST"] == "cdn.example.com"
    assert crawl.config.get("PLUGINS", "") == ""
    assert crawl.config.get("WGET_TIMEOUT") != 77
    assert crawl.config.get("NODE_BINARY") != "/tmp/node"
    assert crawl.config.get("TWOCAPTCHA_API_KEY") != "posted-token"
    assert crawl.config.get("INDEX_ONLY") is not True
    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.schedule is None


def test_add_view_queues_crawl_for_background_runner(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            "url": "https://example.com",
            "tag": "",
            "depth": "0",
            "max_urls": "0",
            "crawl_max_size": "0",
            "snapshot_max_size": "0",
            "url_filters_allowlist": "",
            "url_filters_denylist": "",
            "url_filters_only_new": "1",
            "notes": "",
            "schedule": "",
            "persona": "Default",
            "permissions": "public",
            "start_paused": "",
            "config": "{}",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302
    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is not None
    assert crawl.snapshot_set.count() == 0


def test_add_view_start_paused_creates_paused_crawl_without_snapshots(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            "url": "https://example.com/paused",
            "tag": "",
            "depth": "1",
            "max_urls": "0",
            "crawl_max_size": "0",
            "snapshot_max_size": "0",
            "url_filters_allowlist": "",
            "url_filters_denylist": "",
            "url_filters_only_new": "1",
            "notes": "",
            "schedule": "",
            "persona": "Default",
            "permissions": "public",
            "start_paused": "on",
            "config": "{}",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()
    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.status == Crawl.StatusChoices.PAUSED
    assert crawl.retry_at == RETRY_AT_MAX
    assert crawl.snapshot_set.count() == 0
    assert crawl.config.get("INDEX_ONLY") is not True


def test_add_view_extracts_urls_from_mixed_text_input(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            "url": "\n".join(
                [
                    "https://sweeting.me,https://google.com",
                    "Notes: [ArchiveBox](https://github.com/ArchiveBox/ArchiveBox), https://news.ycombinator.com",
                    "[Wiki](https://en.wikipedia.org/wiki/Classification_(machine_learning))",
                    '{"items":["https://example.com/three"]}',
                    "csv,https://example.com/four",
                ],
            ),
            "tag": "",
            "depth": "0",
            "max_urls": "0",
            "crawl_max_size": "0",
            "snapshot_max_size": "0",
            "url_filters_allowlist": "",
            "url_filters_denylist": "",
            "url_filters_only_new": "1",
            "notes": "",
            "schedule": "",
            "persona": "Default",
            "permissions": "public",
            "start_paused": "",
            "config": "{}",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302

    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.urls == "\n".join(
        [
            "https://sweeting.me",
            "https://google.com",
            "https://github.com/ArchiveBox/ArchiveBox",
            "https://news.ycombinator.com",
            "https://en.wikipedia.org/wiki/Classification_(machine_learning)",
            "https://example.com/three",
            "https://example.com/four",
        ],
    )


def test_add_view_trims_trailing_punctuation_from_markdown_urls(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    client.force_login(admin_user)

    response = client.post(
        reverse("add"),
        data={
            "url": "\n".join(
                [
                    "Docs: https://github.com/ArchiveBox/ArchiveBox.",
                    "Issue: https://github.com/abc?abc#234234?.",
                ],
            ),
            "tag": "",
            "depth": "0",
            "max_urls": "0",
            "crawl_max_size": "0",
            "snapshot_max_size": "0",
            "url_filters_allowlist": "",
            "url_filters_denylist": "",
            "url_filters_only_new": "1",
            "notes": "",
            "schedule": "",
            "persona": "Default",
            "permissions": "public",
            "start_paused": "",
            "config": "{}",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302

    crawl = Crawl.objects.order_by("-created_at").first()
    assert crawl is not None
    assert crawl.urls == "\n".join(
        [
            "https://github.com/ArchiveBox/ArchiveBox",
            "https://github.com/abc?abc#234234",
        ],
    )


def test_add_view_exposes_api_token_for_tag_widget_autocomplete(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_ADD_VIEW", "true")
    client.force_login(admin_user)

    response = client.get(reverse("add"), HTTP_HOST=ADMIN_HOST)

    assert response.status_code == 200
    assert b"window.ARCHIVEBOX_API_KEY" in response.content


def _create_tagged_snapshot(user, *, permissions="public"):
    crawl = Crawl.objects.create(urls="https://example.com", created_by=user, config={"PERMISSIONS": permissions})
    snapshot = Snapshot.from_json({"url": "https://example.com", "tags": "archive"}, overrides={"crawl": crawl})
    assert snapshot is not None
    return snapshot


def test_tags_autocomplete_requires_auth_when_public_index_disabled(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_INDEX", "false")
    _create_tagged_snapshot(admin_user)

    response = client.get(
        reverse("api-1:tags_autocomplete"),
        {"q": "a"},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 401


def test_tags_autocomplete_lists_only_public_snapshot_tags(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_INDEX", "true")
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


def test_tags_autocomplete_allows_authenticated_user_when_public_index_disabled(client, admin_user, monkeypatch):
    monkeypatch.setenv("PUBLIC_INDEX", "false")
    Tag.objects.create(name="archive")
    client.force_login(admin_user)

    response = client.get(
        reverse("api-1:tags_autocomplete"),
        {"q": "a"},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert response.json()["tags"][0]["name"] == "archive"
