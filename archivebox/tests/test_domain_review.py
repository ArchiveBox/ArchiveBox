"""Regression coverage for native domain filtering and management actions."""

import json

import pytest
from django.contrib.messages import get_messages, SUCCESS

from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.test_domain_filters import post_site

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("scope", ["example.com:0", "my_service:8000", "example.com:443", "example.com:80"])
def test_scope_preserves_explicit_host_and_port(scope, crawl):
    from archivebox.core.models import Snapshot
    from archivebox.domains.scope import normalize_site_scope, site_snapshots

    assert normalize_site_scope(scope) == scope
    selected = Snapshot.objects.create(crawl=crawl, url=f"https://{scope}/")
    Snapshot.objects.create(crawl=crawl, url=f"https://{scope.split(':')[0]}/")
    assert list(site_snapshots(scope).values_list("pk", flat=True)) == [selected.pk]


def test_domain_cli_rejects_bad_pattern_without_traceback(capsys):
    from archivebox.core.models import Snapshot

    with pytest.raises(SystemExit) as error:
        Snapshot.objects.filter_by_patterns(["example.com/path"], "domain")
    assert error.value.code == 2
    assert "invalid pattern" in capsys.readouterr().err


@pytest.mark.parametrize("identifier", ["-" * 32, "a" * 33, "a-" * 16])
def test_invalid_domain_identifiers_return_not_found(admin_client, identifier):
    response = admin_client.get(f"/admin/domains/{identifier}/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 404


def test_domain_export_rejects_mixed_prefix_selection(admin_client):
    from archivebox.machine.models import Process

    response = admin_client.post(
        "/admin/domains/actions/",
        {"action": "export", "export_format": "html", "_selected_action": ["example.com/docs", "other.com"]},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 400
    assert not Process.objects.filter(worker_type="site-export").exists()


def test_include_subdomains_overrides_default_same_host_toggle(admin_client):
    from archivebox.crawls.models import Crawl

    response = post_site(admin_client, include_subdomains="on", url_filters_same_domain_only="on")
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert crawl.url_passes_filters("https://sub.example.com/docs")
    assert not crawl.url_passes_filters("https://example.com.evil.test/docs")


def test_explicit_allowlist_replaces_default_domain_scope(admin_client):
    from archivebox.crawls.models import Crawl

    response = post_site(admin_client, url_filters_subpaths_only="on", url_filters_allowlist="(?i)story")
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert crawl.config["URL_ALLOWLIST"] == "(?i)story"
    assert crawl.url_passes_filters("https://example.com/outside/STORY")
    assert crawl.url_passes_filters("https://other.example/story")
    assert not crawl.url_passes_filters("https://example.com/docs/no-match")


def test_explicit_empty_native_filters_clear_generic_config(admin_client):
    from archivebox.crawls.models import Crawl

    response = admin_client.post(
        "/add/",
        {
            "url": "https://example.com/",
            "depth": "0",
            "permissions": "private",
            "url_filters_allowlist": "",
            "url_filters_denylist": "",
            "config": json.dumps({"URL_ALLOWLIST": "other.example", "URL_DENYLIST": "example.com"}),
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302, response.context["form"].errors
    crawl = Crawl.objects.get()
    assert crawl.config["URL_ALLOWLIST"] == ""
    assert crawl.config["URL_DENYLIST"] == ""
    assert crawl.url_passes_filters("https://example.com/")


def test_replay_toggle_preserves_config_changed_after_machine_cache(admin_client):
    from archivebox.machine.models import Machine

    cached = Machine.current()
    updated = {**cached.config, "TIMEOUT": 127}
    Machine.objects.filter(pk=cached.pk).update(config=updated)
    response = admin_client.post(
        "/admin/domains/site/replay-settings/",
        {"scope": "example.com", "rewrite_archived_links": "on"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    assert Machine.objects.get(pk=cached.pk).config == {**updated, "REWRITE_ARCHIVED_LINKS": True}


def test_repeated_pause_does_not_report_success(admin_client):
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(urls="https://example.com/", tags_str="site-clone", status="paused")
    response = admin_client.post(f"/admin/domains/{crawl.pk}/pause/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    assert all(message.level != SUCCESS for message in get_messages(response.wsgi_request))
    crawl.refresh_from_db()
    assert crawl.status == "paused"
