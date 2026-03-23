import pytest
from typing import cast

from django.contrib.auth import get_user_model
from django.contrib.auth.models import UserManager
from django.urls import reverse

from archivebox.personas.importers import (
    PersonaImportResult,
    discover_persona_template_profiles,
    import_persona_from_source,
    resolve_browser_profile_source,
    resolve_custom_import_source,
)


pytestmark = pytest.mark.django_db

User = get_user_model()
ADMIN_HOST = "admin.archivebox.localhost:8000"


@pytest.fixture
def admin_user(db):
    return cast(UserManager, User.objects).create_superuser(
        username="personaadmin",
        email="personaadmin@test.com",
        password="testpassword",
    )


def _make_profile_source(tmp_path):
    user_data_dir = tmp_path / "Chrome User Data"
    profile_dir = user_data_dir / "Default"
    profile_dir.mkdir(parents=True)
    (profile_dir / "Preferences").write_text("{}")
    return resolve_browser_profile_source(
        browser="chrome",
        user_data_dir=user_data_dir,
        profile_dir="Default",
        browser_binary="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
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


def test_discover_persona_template_profiles_finds_home_abx_personas(monkeypatch, tmp_path):
    from archivebox.config.constants import CONSTANTS

    monkeypatch.setattr(CONSTANTS, "PERSONAS_DIR", tmp_path / "missing-data-personas")
    monkeypatch.setattr("archivebox.personas.importers.Path.home", lambda: tmp_path)

    chrome_profile = tmp_path / ".config" / "abx" / "personas" / "HomePersona" / "chrome_profile"
    default_profile = chrome_profile / "Default"
    default_profile.mkdir(parents=True)
    (default_profile / "Preferences").write_text("{}")

    discovered = discover_persona_template_profiles()

    assert len(discovered) == 1
    assert discovered[0].browser == "persona"
    assert discovered[0].source_name == "HomePersona"
    assert discovered[0].profile_dir == "Default"
    assert discovered[0].user_data_dir == chrome_profile.resolve()


def test_persona_admin_add_view_renders_import_ui(client, admin_user, monkeypatch, tmp_path):
    source = _make_profile_source(tmp_path)
    monkeypatch.setattr("archivebox.personas.forms.discover_local_browser_profiles", lambda: [source])
    monkeypatch.setattr("archivebox.personas.admin.discover_local_browser_profiles", lambda: [source])

    client.login(username="personaadmin", password="testpassword")
    response = client.get(reverse("admin:personas_persona_add"), HTTP_HOST=ADMIN_HOST)

    assert response.status_code == 200
    assert b"Bootstrap a persona from a real browser session" in response.content
    assert b"Google Chrome / Default" in response.content
    assert b"auth.json" in response.content


def test_import_persona_from_source_copies_user_agent_to_persona_config(admin_user, monkeypatch, tmp_path):
    from archivebox.personas.models import Persona

    source = _make_profile_source(tmp_path)
    persona = Persona.objects.create(name="AgentPersona", created_by=admin_user)

    def fake_export_browser_state(**kwargs):
        return True, {"user_agent": "Mozilla/5.0 Test Imported UA"}, "ok"

    monkeypatch.setattr("archivebox.personas.importers.export_browser_state", fake_export_browser_state)

    result = import_persona_from_source(
        persona,
        source,
        copy_profile=False,
        import_cookies=False,
        capture_storage=False,
    )

    persona.refresh_from_db()
    assert result.user_agent_imported is True
    assert persona.config["USER_AGENT"] == "Mozilla/5.0 Test Imported UA"


def test_persona_admin_add_post_runs_shared_importer(client, admin_user, monkeypatch, tmp_path):
    from archivebox.personas.models import Persona

    source = _make_profile_source(tmp_path)
    monkeypatch.setattr("archivebox.personas.forms.discover_local_browser_profiles", lambda: [source])
    monkeypatch.setattr("archivebox.personas.admin.discover_local_browser_profiles", lambda: [source])

    calls = {}

    def fake_import(persona, selected_source, **kwargs):
        calls["persona_name"] = persona.name
        calls["source"] = selected_source
        calls["kwargs"] = kwargs
        (persona.path / "cookies.txt").parent.mkdir(parents=True, exist_ok=True)
        (persona.path / "cookies.txt").write_text("# Netscape HTTP Cookie File\n")
        (persona.path / "auth.json").write_text('{"TYPE":"auth","cookies":[],"localStorage":{},"sessionStorage":{}}\n')
        return PersonaImportResult(
            source=selected_source,
            profile_copied=True,
            cookies_imported=True,
            storage_captured=True,
        )

    monkeypatch.setattr("archivebox.personas.forms.import_persona_from_source", fake_import)

    client.login(username="personaadmin", password="testpassword")
    response = client.post(
        reverse("admin:personas_persona_add"),
        {
            "name": "ImportedPersona",
            "created_by": str(admin_user.pk),
            "config": "{}",
            "import_mode": "discovered",
            "import_discovered_profile": source.choice_value,
            "import_copy_profile": "on",
            "import_extract_cookies": "on",
            "import_capture_storage": "on",
            "_save": "Save",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302
    persona = Persona.objects.get(name="ImportedPersona")
    assert calls["persona_name"] == "ImportedPersona"
    assert calls["source"].profile_dir == "Default"
    assert calls["kwargs"] == {
        "copy_profile": True,
        "import_cookies": True,
        "capture_storage": True,
    }
    assert persona.COOKIES_FILE.endswith("cookies.txt")
    assert persona.AUTH_STORAGE_FILE.endswith("auth.json")
