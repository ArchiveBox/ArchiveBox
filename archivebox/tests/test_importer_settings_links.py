"""Importer setup links point to effective existing settings without leaking secrets."""

import pytest
from django.urls import reverse

from archivebox.importers.models import ImporterRun, ImporterSource
from archivebox.machine.models import Machine
from archivebox.personas.models import Persona
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db
PANEL = "#plugin-panel-importers_plugins-importer_search"


@pytest.mark.parametrize("feed", ("kagi", "brave", "exa"))
def test_search_setup_links_to_machine_defaults(admin_client, feed):
    machine = Machine.current()
    page = admin_client.get(reverse("importers:new", args=["importer_search", feed]), HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200
    assert (reverse("admin:machine_machine_change", args=[machine.pk]) + PANEL).encode() in page.content
    assert b'name="setting_' + feed.upper().encode() + b'_SEARCH_API_KEY"' not in page.content


def test_no_credentials_link_for_duckduckgo(admin_client):
    page = admin_client.get(reverse("importers:new", args=["importer_search", "duckduckgo"]), HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200
    assert PANEL.encode() not in page.content


def test_configured_persona_link_and_safe_error_details(admin_client, admin_user):
    secret = "dummy-key-must-never-render"
    persona = Persona.objects.create(name="Kagi Test Persona", config={"KAGI_SEARCH_API_KEY": secret})
    source = ImporterSource.objects.create(
        name="Kagi test",
        plugin="importer_search",
        feed="kagi",
        persona=persona,
        created_by=admin_user,
        settings={"SEARCH_QUERY": "example"},
    )
    run = ImporterRun.objects.create(
        source=source,
        action=ImporterRun.Action.PREVIEW,
        status=ImporterRun.Status.NEEDS_LOGIN,
        message="Configure KAGI_SEARCH_API_KEY in Search plugin settings.",
    )
    target = reverse("admin:personas_persona_change", args=[persona.pk]) + PANEL
    for endpoint in (reverse("importers:edit", args=[source.pk]), reverse("importers:run", args=[run.pk])):
        page = admin_client.get(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
        assert page.status_code == 200
        assert target.encode() in page.content
        assert secret.encode() not in page.content
        assert b'name="setting_KAGI_SEARCH_API_KEY"' not in page.content
    settings = admin_client.get(target.split("#", 1)[0], HTTP_HOST=ADMIN_TEST_HOST)
    assert settings.status_code == 200
    assert PANEL[1:].encode() in settings.content
    assert secret.encode() not in settings.content

    from archivebox.importers.diagnostics import run_directory

    directory = run_directory(run)
    directory.mkdir(parents=True)
    (directory / "command-error.log").write_text(secret)

    response = admin_client.get(reverse("importers:run-activity", args=[run.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    html = response.json()["html"]
    assert target in html
    assert run.message in html
    assert "Needs configuration" in html
    assert "command-error.log" in html
    assert secret not in html
    assert "No discovered items were saved." in html
    history = admin_client.get(reverse("importers:source-activity", args=[source.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert history.status_code == 200
    assert secret not in history.json()["html"]
    log = admin_client.get(reverse("importers:run-log", args=[run.pk, "command-error.log"]), HTTP_HOST=ADMIN_TEST_HOST)
    assert log.status_code == 200
    assert b"".join(log.streaming_content) == secret.encode()


def test_x_bookmark_setup_links_to_persona_browser_state(admin_client, admin_user):
    configure = admin_client.get(reverse("importers:new", args=["importers_browser", "x_bookmarks"]), HTTP_HOST=ADMIN_TEST_HOST)
    assert configure.status_code == 200
    assert reverse("admin:personas_persona_changelist").encode() in configure.content
    assert b"Set up a Persona" in configure.content
    persona = Persona.objects.create(name="Browser Persona")
    source = ImporterSource.objects.create(
        name="X bookmarks",
        plugin="importers_browser",
        feed="x_bookmarks",
        persona=persona,
        created_by=admin_user,
    )
    persona_url = reverse("admin:personas_persona_change", args=[persona.pk])
    edit = admin_client.get(reverse("importers:edit", args=[source.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert edit.status_code == 200
    assert (persona_url + "#persona-browser-state").encode() in edit.content
    assert b"Open Persona browser state" in edit.content
    detail = admin_client.get(source.get_absolute_url(), HTTP_HOST=ADMIN_TEST_HOST)
    assert detail.status_code == 200
    assert f'href="{persona_url}">Browser Persona</a>'.encode() in detail.content
    assert b"#persona-browser-state" not in detail.content
    assert b"Open Persona browser state" not in detail.content
    settings = admin_client.get(persona_url, HTTP_HOST=ADMIN_TEST_HOST)
    assert settings.status_code == 200
    assert b'id="persona-browser-state"' in settings.content
