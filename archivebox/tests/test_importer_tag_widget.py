"""Importer tags reuse the normal admin editor without changing source semantics."""

import pytest

from archivebox.core.models import Tag
from archivebox.core.widgets import TagEditorWidget
from archivebox.importers.catalog import get_importers
from archivebox.importers.forms import ImporterSourceForm
from archivebox.importers.models import ImporterSource
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def test_all_importer_forms_reuse_tag_editor(admin_user):
    definitions = get_importers()
    assert definitions
    for definition in definitions.values():
        source = ImporterSource(created_by=admin_user, tags="Existing tag,Second")
        form = ImporterSourceForm(instance=source, definition=definition)
        assert isinstance(form.fields["tags"].widget, TagEditorWidget), definition.plugin
        rendered = str(form["tags"])
        assert 'id="id_tags_input"' in rendered
        assert 'list="id_tags_datalist"' in rendered
        assert 'type="hidden" name="tags"' in rendered
        assert 'data-tag="Existing tag"' in rendered
        assert "/api/v1/core/tags/autocomplete/" in rendered
        assert form.fields["tags"].required is False


def test_importer_tag_editor_roundtrip_validation_and_authenticated_suggestions(admin_client):
    from django.test import Client

    client = Client()
    Tag.objects.create(name="Existing tag")
    url = "/admin/importers/new/importer_rss/feed/"
    page = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200
    assert b'id="id_tags_input"' in page.content
    assert b"window.ARCHIVEBOX_API_KEY" in page.content
    assert client.get(url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    suggestions = admin_client.get("/api/v1/core/tags/autocomplete/", {"q": "Existing"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert suggestions.status_code == 200
    assert "Existing tag" in [tag["name"] for tag in suggestions.json()["tags"]]

    data = {"name": "Tagged importer", "tags": "Existing tag,New tag", "setting_IMPORTER_RSS_URL": "not a URL"}
    invalid = admin_client.post(url, data, HTTP_HOST=ADMIN_TEST_HOST)
    assert invalid.status_code == 200
    assert b'data-tag="Existing tag"' in invalid.content
    assert b'data-tag="New tag"' in invalid.content
    assert not ImporterSource.objects.filter(name="Tagged importer").exists()
    data["setting_IMPORTER_RSS_URL"] = "https://example.org/feed.xml"
    saved = admin_client.post(url, data, HTTP_HOST=ADMIN_TEST_HOST)
    assert saved.status_code == 302
    source = ImporterSource.objects.get(name="Tagged importer")
    assert source.tags == "Existing tag,New tag"
    assert source.settings == {"IMPORTER_RSS_URL": data["setting_IMPORTER_RSS_URL"]}
    assert source.checkpoint == {}
    edit_url = f"/admin/importers/{source.pk}/edit/"
    edit = admin_client.get(edit_url, HTTP_HOST=ADMIN_TEST_HOST)
    assert edit.status_code == 200
    assert b'data-tag="New tag"' in edit.content
    data["tags"] = ""
    assert admin_client.post(edit_url, data, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    source.refresh_from_db()
    assert source.tags == ""
