import pytest
from django.urls import reverse

from archivebox.cli.archivebox_add import add
from archivebox.config.common import get_config
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.plugins.discovery import get_enabled_plugins
from archivebox.plugins.selection import parse_plugin_selection
from archivebox.services.process_service import normalize_process_env
from archivebox.tests.test_ui_add_view import ADD_FORM_DEFAULTS, ADMIN_HOST

pytestmark = pytest.mark.django_db


def test_capture_plan_distinguishes_inherit_from_empty(admin_client, admin_user, monkeypatch):
    monkeypatch.setenv("ARCHIVEWEBPAGE_ENABLED", "true")
    monkeypatch.setenv("RESPONSES_ENABLED", "false")
    Persona.get_or_create_default()
    cli_defaults, _ = add(urls=["https://example.test/cli-inherited"], bg=True, created_by_id=admin_user.pk)
    cli_empty, _ = add(urls=["https://example.test/cli-empty"], plugins="[]", bg=True, created_by_id=admin_user.pk)

    def submit(path, **fields):
        response = admin_client.post(
            reverse("add"),
            data={**ADD_FORM_DEFAULTS, "crawl_max_concurrent_snapshots": "0", "url": f"https://example.test/{path}", **fields},
            HTTP_HOST=ADMIN_HOST,
        )
        assert response.status_code == 302
        return Crawl.objects.get(urls=f"https://example.test/{path}")

    rendered = admin_client.get(reverse("add"), HTTP_HOST=ADMIN_HOST)
    assert rendered.status_code == 200
    assert b'class="plugin-section-toggle plugin-title-toggle"' in rendered.content
    assert b'name="capture_plugins"' not in rendered.content
    assert b'<option value="PLUGINS">' not in rendered.content
    # A submission with all checkboxes cleared contains no plugin selector.
    web_defaults = submit("web-inherited", config='{"PLUGINS": "[]"}')
    web_empty = submit("web-empty", capture_plugins="explicit", config='{"PLUGINS": ""}')
    assert cli_defaults.config["PLUGINS"] == web_defaults.config["PLUGINS"] == ""
    assert cli_empty.config["PLUGINS"] == web_empty.config["PLUGINS"] == "[]"
    for crawl in (cli_defaults, web_defaults):
        assert "archivewebpage" in get_enabled_plugins(config=get_config(crawl=crawl))
    for crawl in (cli_empty, web_empty):
        active = get_enabled_plugins(config=get_config(crawl=crawl))
        assert {"archivewebpage", "responses", "chrome", "readability"}.isdisjoint(active), active
    env = normalize_process_env({"PLUGINS": "[]"})
    assert "PLUGINS" not in env
    assert env["ARCHIVEWEBPAGE_ENABLED"] == env["RESPONSES_ENABLED"] == "False"


def test_plugin_selector_normalizes_at_the_configuration_boundary():
    assert parse_plugin_selection("") is None
    assert parse_plugin_selection(" [] ") == []
    assert parse_plugin_selection(' ["Title", " title ", "wget"] ') == ["title", "wget"]
    assert parse_plugin_selection(" title , WGET, title ") == ["title", "wget"]
