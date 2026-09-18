import pytest

from django.urls import reverse

from archivebox.personas.importers import (
    discover_persona_template_profiles,
    import_persona_from_source,
    resolve_browser_profile_source,
    resolve_custom_import_source,
)
from archivebox.personas.models import Persona
from archivebox.tests.conftest import ADMIN_TEST_HOST


pytestmark = pytest.mark.django_db


def _make_profile_source(tmp_path):
    user_data_dir = tmp_path / "Chrome User Data"
    profile_dir = user_data_dir / "Default"
    profile_dir.mkdir(parents=True)
    (profile_dir / "Preferences").write_text("{}")
    return resolve_browser_profile_source(
        browser="chrome",
        user_data_dir=user_data_dir,
        profile_dir="Default",
        browser_binary="/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    )


def _make_persona_template_source(name="TemplatePersona"):
    from archivebox.config.constants import CONSTANTS

    user_data_dir = CONSTANTS.PERSONAS_DIR / name / "chrome_profile"
    profile_dir = user_data_dir / "Default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "Preferences").write_text('{"profile":{"name":"Default"}}')
    (profile_dir / "Bookmarks").write_text('{"roots":{}}')
    (profile_dir / "Cache").mkdir(exist_ok=True)
    (profile_dir / "Cache" / "volatile").write_text("skip")
    return next(
        profile for profile in discover_persona_template_profiles(personas_dir=CONSTANTS.PERSONAS_DIR) if profile.source_name == name
    )


def test_resolve_custom_import_source_accepts_exact_profile_dir(tmp_path):
    user_data_dir = tmp_path / "Brave User Data"
    profile_dir = user_data_dir / "Profile 2"
    profile_dir.mkdir(parents=True)
    (profile_dir / "Preferences").write_text("{}")

    source = resolve_custom_import_source(str(profile_dir))

    assert source.kind == "browser-profile"
    assert source.user_data_dir == user_data_dir.resolve()
    assert source.profile_dir == "Profile 2"


def test_resolve_custom_import_source_accepts_cdp_url():
    source = resolve_custom_import_source("ws://127.0.0.1:9222/devtools/browser/test-session")

    assert source.kind == "cdp"
    assert source.cdp_url == "ws://127.0.0.1:9222/devtools/browser/test-session"


def test_discover_persona_template_profiles_finds_chrome_profile_dirs(tmp_path):
    personas_dir = tmp_path / "personas"
    chrome_profile = personas_dir / "ExistingPersona" / "chrome_profile"
    default_profile = chrome_profile / "Default"
    default_profile.mkdir(parents=True)
    (default_profile / "Preferences").write_text("{}")

    discovered = discover_persona_template_profiles(personas_dir=personas_dir)

    assert len(discovered) == 1
    assert discovered[0].browser == "persona"
    assert discovered[0].source_name == "ExistingPersona"
    assert discovered[0].profile_dir == "Default"
    assert discovered[0].user_data_dir == chrome_profile.resolve()


def test_discover_persona_template_profiles_finds_data_dir_personas():
    from archivebox.config.constants import CONSTANTS

    source = _make_persona_template_source("DataDirPersona")

    discovered = discover_persona_template_profiles()

    matching = [profile for profile in discovered if profile.source_name == "DataDirPersona"]
    assert len(matching) == 1
    assert matching[0].browser == "persona"
    assert matching[0].profile_dir == "Default"
    assert matching[0].user_data_dir == source.user_data_dir
    assert matching[0].user_data_dir.parent.parent == CONSTANTS.PERSONAS_DIR.resolve()


def test_persona_admin_add_view_skips_unreadable_chrome_profile_entries(admin_client):
    from archivebox.config.constants import CONSTANTS

    chrome_profile = CONSTANTS.PERSONAS_DIR / "UnreadableTemplatePersona" / "chrome_profile"
    default_profile = chrome_profile / "Default"
    default_profile.mkdir(parents=True, exist_ok=True)
    (default_profile / "Preferences").write_text('{"profile":{"name":"Default"}}')
    unreadable_dir = chrome_profile / "ActorSafetyLists"
    unreadable_dir.mkdir(parents=True, exist_ok=True)
    (unreadable_dir / "Preferences").write_text("{}")
    unreadable_dir.chmod(0)

    try:
        response = admin_client.get(reverse("admin:personas_persona_add"), HTTP_HOST=ADMIN_TEST_HOST)
    finally:
        unreadable_dir.chmod(0o700)

    assert response.status_code == 200
    assert b"UnreadableTemplatePersona" in response.content
    assert b"Persona Template" in response.content


def test_persona_admin_add_view_renders_import_ui(admin_client):
    source = _make_persona_template_source("RenderImportPersona")

    response = admin_client.get(reverse("admin:personas_persona_add"), HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    assert source.source_name.encode() in response.content
    assert b"Persona Template" in response.content
    assert b"auth.json" in response.content
    assert b"Plugin Config" in response.content
    assert b'name="plugin_config__wget__WGET_TIMEOUT"' in response.content
    assert b'<fieldset id="plugin-config" class="module aligned wide persona-plugin-config">' in response.content
    assert b'href="https://archivebox.github.io/archivebox-browser-extension/"' in response.content
    assert b"import cookies into this persona from another browser" in response.content
    assert "wide" in response.context["adminform"].fieldsets[0][1]["classes"]


def test_import_persona_from_source_copies_profile_without_browser_export(admin_user):
    from archivebox.personas.models import Persona

    source = _make_persona_template_source("ImporterTemplatePersona")
    persona = Persona.objects.create(name="AgentPersona", created_by=admin_user)

    result = import_persona_from_source(
        persona,
        source,
        copy_profile=True,
        import_cookies=False,
        capture_storage=False,
    )

    copied_profile = persona.path / "chrome_profile" / "Default"
    assert result.profile_copied is True
    assert result.cookies_imported is False
    assert result.storage_captured is False
    assert result.user_agent_imported is False
    assert (copied_profile / "Preferences").read_text() == '{"profile":{"name":"Default"}}'
    assert not (copied_profile / "Cache").exists()


def test_persona_admin_add_post_runs_shared_importer(admin_client, admin_user):
    from archivebox.personas.models import Persona

    source = _make_persona_template_source("AdminPostTemplatePersona")

    response = admin_client.post(
        reverse("admin:personas_persona_add"),
        {
            "name": "ImportedPersona",
            "created_by": str(admin_user.pk),
            "permissions": "public",
            "config": "{}",
            "import_mode": "discovered",
            "import_discovered_profile": source.choice_value,
            "import_copy_profile": "on",
            "_save": "Save",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 302
    persona = Persona.objects.get(name="ImportedPersona")
    assert (persona.path / "chrome_profile" / "Default" / "Preferences").exists()
    assert not persona.COOKIES_FILE
    assert not persona.AUTH_STORAGE_FILE


def test_persona_admin_unset_cookie_paths_stay_unset(admin_client, admin_user):
    from html.parser import HTMLParser

    paths = {}

    class CookiePathInputs(HTMLParser):
        def handle_starttag(self, tag, attrs):
            field = dict(attrs)
            name = field.get("name", "")
            if tag == "input" and name.startswith("plugin_config__") and name.endswith(("__COOKIES_FILE", "__AUTH_STORAGE_FILE")):
                paths[name] = field.get("value", "")

    url = reverse("admin:personas_persona_add")
    page = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
    CookiePathInputs().feed(page.content.decode())
    assert paths
    assert all(value == "" for value in paths.values())
    response = admin_client.post(
        url,
        {
            "name": "UnsetCookiePaths",
            "created_by": str(admin_user.pk),
            "permissions": "private",
            "config": "{}",
            "import_mode": "none",
            "_save": "Save",
            **paths,
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    config = Persona.objects.get(name="UnsetCookiePaths").config
    assert "COOKIES_FILE" not in config
    assert "AUTH_STORAGE_FILE" not in config


def test_persona_admin_saves_typed_plugin_config(admin_client, admin_user):
    add_response = admin_client.get(reverse("admin:personas_persona_add"), HTTP_HOST=ADMIN_TEST_HOST)
    add_form = add_response.context["adminform"].form
    exposed_config_keys = {field["key"] for group in add_form.plugin_groups for card in group["plugins"] for field in card["config_fields"]}
    assert {key for key in exposed_config_keys if key.endswith("_BINARY")}
    assert (
        not {
            "ARCHIVE_DIR",
            "USERS_DIR",
            "PERSONAS_DIR",
            "CUSTOM_TEMPLATES_DIR",
        }
        & exposed_config_keys
    )

    response = admin_client.post(
        reverse("admin:personas_persona_add"),
        {
            "name": "PluginConfigPersona",
            "created_by": str(admin_user.pk),
            "permissions": "public",
            "config": "{}",
            "import_mode": "none",
            "plugin_config__wget__WGET_TIMEOUT": "77",
            "plugin_config__wget__WGET_WARC_ENABLED": "false",
            "_save": "Save",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 302
    persona = Persona.objects.get(name="PluginConfigPersona")
    assert persona.config["WGET_TIMEOUT"] == 77
    assert persona.config["WGET_WARC_ENABLED"] is False


def test_persona_config_save_heals_json_encoded_string_values(admin_user):
    persona = Persona.objects.create(
        name="QuotedConfigPersona",
        created_by=admin_user,
        config={
            "EXTRA_CONTEXT": 'prefix "inner" suffix',
            "USER_AGENT": '"ArchiveBox \\"Quoted\\" Agent"',
        },
    )

    persona.refresh_from_db()

    assert persona.config["EXTRA_CONTEXT"] == 'prefix "inner" suffix'
    assert persona.config["USER_AGENT"] == 'ArchiveBox "Quoted" Agent'
