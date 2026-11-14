"""Native source forms and REST updates share persistence and concurrency rules."""

import pytest

from archivebox.importers.catalog import get_importer
from archivebox.importers.forms import ImporterSourceForm
from archivebox.importers.models import ImporterSource
from archivebox.importers.service import run_next_importer
from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.test_importers import import_site as import_site

pytestmark = pytest.mark.django_db(transaction=True)


def test_validated_form_cannot_overwrite_a_started_import(admin_client, import_site):
    _, origin = import_site
    assert (
        admin_client.post(
            "/admin/importers/new/importer_rss/feed/",
            {"name": "Original", "setting_IMPORTER_RSS_URL": f"{origin}/feed.xml"},
            HTTP_HOST=ADMIN_TEST_HOST,
        ).status_code
        == 302
    )
    source = ImporterSource.objects.get()
    form = ImporterSourceForm(
        {"name": "Changed", "setting_IMPORTER_RSS_URL": f"{origin}/feed.xml", "schedule": "daily"},
        instance=source,
        definition=get_importer(source.plugin, source.feed),
    )
    assert form.is_valid(), form.errors
    assert admin_client.post(f"/admin/importers/{source.pk}/import/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    unsaved = form.save(commit=False)
    assert unsaved.name == "Changed"
    assert ImporterSource.objects.get(pk=source.pk).name == "Original"
    with pytest.raises(ValueError, match="active|progress"):
        form.save()
    source.refresh_from_db()
    assert source.name == "Original" and source.next_run_at is None
    assert run_next_importer()
    source.refresh_from_db()
    checkpoint = source.checkpoint
    assert checkpoint
    # Finishing the run must not make the stale form's original progress current.
    with pytest.raises(ValueError, match="active|progress"):
        form.save()
    source.refresh_from_db()
    assert source.name == "Original" and source.checkpoint == checkpoint


def test_validated_form_cannot_undo_a_concurrent_pause(client, api_headers, import_site):
    _, origin = import_site
    response = client.post(
        "/api/v1/importers/sources",
        {"plugin": "importer_rss", "feed": "feed", "settings": {"IMPORTER_RSS_URL": f"{origin}/feed.xml"}, "schedule": "daily"},
        content_type="application/json",
        **api_headers,
    )
    assert response.status_code == 200, response.content
    source = ImporterSource.objects.get(pk=response.json()["id"])
    original_name = source.name
    form = ImporterSourceForm(
        {"name": "Changed", "setting_IMPORTER_RSS_URL": f"{origin}/feed.xml", "schedule": "daily"},
        instance=source,
        definition=get_importer(source.plugin, source.feed),
    )
    assert form.is_valid(), form.errors
    assert client.post(f"/api/v1/importers/source/{source.pk}/pause", **api_headers).status_code == 200
    with pytest.raises(ValueError, match="schedule changed"):
        form.save()
    source.refresh_from_db()
    assert not source.enabled and source.next_run_at is None
    assert source.name == original_name


@pytest.mark.parametrize("surface", ["ui", "api"])
def test_source_edit_preserves_progress_and_paused_schedule(admin_client, client, api_headers, import_site, surface):
    _, origin = import_site
    from archivebox.core.models import Folder
    from archivebox.personas.models import Persona

    folder = Folder.objects.create(name="Imported links")
    persona = Persona.get_or_create_named("Source settings")
    settings = {"IMPORTER_RSS_URL": f"{origin}/feed.xml"}
    values = {
        "name": "Reading",
        "settings": settings,
        "folder_id": str(folder.pk),
        "persona_id": str(persona.pk),
        "limit": 25,
        "schedule": "daily",
        "tags": "Manual",
    }
    source = None

    def save(values, *, expected):
        if surface == "api":
            path = f"/api/v1/importers/source/{source.pk}" if source else "/api/v1/importers/sources"
            payload = values if source else {"plugin": "importer_rss", "feed": "feed", **values}
            response = (client.patch if source else client.post)(path, payload, content_type="application/json", **api_headers)
            assert response.status_code == expected, response.content
        else:
            path = f"/admin/importers/{source.pk}/edit/" if source else "/admin/importers/new/importer_rss/feed/"
            payload = {key: value for key, value in values.items() if key not in {"settings", "folder_id", "persona_id"}}
            payload.update(folder=values["folder_id"], persona=values["persona_id"])
            payload.update({f"setting_{key}": value for key, value in values["settings"].items()})
            response = admin_client.post(path, payload, HTTP_HOST=ADMIN_TEST_HOST)
            assert response.status_code == expected, response.content
        return response

    save(values, expected=200 if surface == "api" else 302)
    source = ImporterSource.objects.get(name="Reading")
    assert source.next_run_at and source.schedule == "0 0 * * *"
    assert source.folder_id == folder.pk and source.persona_id == persona.pk
    assert source.limit == 25 and source.tags == "Manual"
    assert client.post(f"/api/v1/importers/source/{source.pk}/import", **api_headers).status_code == 200
    assert run_next_importer()
    source.refresh_from_db()
    checkpoint = source.checkpoint
    assert checkpoint
    bad = {**values, "settings": {"IMPORTER_RSS_URL": f"{origin}/different.xml"}}
    response = save(bad, expected=400 if surface == "api" else 200)
    assert b"Reset progress" in response.content
    other_persona = Persona.get_or_create_named("Other account")
    response = save({**values, "persona_id": str(other_persona.pk)}, expected=400 if surface == "api" else 200)
    assert b"Reset progress" in response.content
    source.refresh_from_db()
    assert source.settings == settings and source.checkpoint == checkpoint and source.persona_id == persona.pk
    assert client.post(f"/api/v1/importers/source/{source.pk}/pause", **api_headers).status_code == 200
    changed = {"name": "Renamed"} if surface == "api" else {**values, "name": "Renamed"}
    save(changed, expected=200 if surface == "api" else 302)
    source.refresh_from_db()
    assert source.name == "Renamed" and not source.enabled and source.next_run_at is None
    assert source.folder_id == folder.pk and source.persona_id == persona.pk
    assert source.settings == settings and source.checkpoint == checkpoint
