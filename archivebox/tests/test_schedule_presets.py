"""Schedule shortcuts preserve real form validation and native editable inputs."""

from html.parser import HTMLParser

import pytest
from django import forms

from archivebox.core.forms import AddLinkForm
from archivebox.crawls.admin import CrawlAdminForm, CrawlScheduleAdminForm
from archivebox.domains.forms import DomainCrawlForm
from archivebox.importers.forms import ImporterSourceForm
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.mark.parametrize("form_class", [AddLinkForm, DomainCrawlForm, ImporterSourceForm, CrawlScheduleAdminForm])
def test_schedule_widget_preserves_field_and_media(form_class):
    from archivebox.importers.catalog import get_importers

    kwargs = {"definition": next(iter(get_importers().values()))} if form_class is ImporterSourceForm else {}
    form = form_class(prefix="first", initial={"schedule": "0 */6 * * *"}, **kwargs)
    field = form.fields["schedule"]
    assert isinstance(field.widget, forms.TextInput)
    elements = Elements(str(form["schedule"])).elements
    inputs = [attrs for tag, attrs in elements if tag == "input"]
    assert len(inputs) == 1
    assert inputs[0]["name"] == "first-schedule"
    assert inputs[0]["id"] == "id_first-schedule"
    assert inputs[0]["value"] == "0 */6 * * *"
    assert inputs[0]["type"] == "text"
    buttons = [attrs for tag, attrs in elements if tag == "button"]
    assert [b["data-schedule-preset"] for b in buttons] == ["daily", "weekly"]
    assert all(b["type"] == "button" and b["aria-label"] for b in buttons)
    ids = [attrs["id"] for _, attrs in elements if "id" in attrs]
    assert ids == ["id_first-schedule"]
    media = str(form.media + form_class(prefix="second", **kwargs).media)
    assert media.count("schedule-presets.js") == 1
    assert media.count("schedule-presets.css") == 1


@pytest.mark.parametrize("url", ["/add/", "/admin/domains/", "/admin/importers/new/importer_rss/feed/"])
def test_schedule_routes_include_shortcuts_and_media(admin_client, url):
    response = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    html = response.content.decode()
    assert 'data-schedule-preset="daily"' in html
    assert 'data-schedule-preset="weekly"' in html
    assert html.count("schedule-presets.js") == 1
    assert html.count("schedule-presets.css") == 1


def test_importer_schedule_validation_is_unchanged(admin_client):
    from archivebox.importers.models import ImporterSource

    url = "/admin/importers/new/importer_rss/feed/"
    data = {"name": "Scheduled source", "setting_IMPORTER_RSS_URL": "https://example.org/feed.xml", "schedule": "not a schedule"}
    invalid = admin_client.post(url, data, HTTP_HOST=ADMIN_TEST_HOST)
    assert invalid.status_code == 200
    assert not ImporterSource.objects.filter(name=data["name"]).exists()
    assert 'value="not a schedule"' in invalid.content.decode()
    data["schedule"] = "weekly"
    assert admin_client.post(url, data, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    source = ImporterSource.objects.get(name=data["name"])
    assert source.schedule == "0 0 * * 0"


def test_crawl_schedule_relationship_is_not_a_text_shortcut():
    assert isinstance(CrawlAdminForm.base_fields["schedule"], forms.ModelChoiceField)
    assert "schedule-presets" not in str(CrawlAdminForm.base_fields["schedule"].widget.media)


def test_schedule_admin_edit_route_keeps_media_and_native_input(admin_client, admin_user):
    from archivebox.crawls.models import Crawl, CrawlSchedule

    crawl = Crawl.objects.create(urls="https://example.org/", created_by=admin_user)
    schedule = CrawlSchedule.objects.create(template=crawl, schedule="daily", created_by=admin_user)
    response = admin_client.get(schedule.admin_change_url, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    html = response.content.decode()
    assert 'data-schedule-preset="daily"' in html
    assert 'data-schedule-preset="weekly"' in html
    assert html.count("schedule-presets.js") == 1
    assert html.count("schedule-presets.css") == 1
    assert 'name="schedule"' in html
