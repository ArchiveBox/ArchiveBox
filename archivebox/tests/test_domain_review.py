"""Regression coverage for native domain filtering and management actions."""

import json

import pytest
from django.contrib.messages import get_messages, SUCCESS

from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.test_domain_filters import post_site

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize(
    ("scope", "normalized"),
    [
        ("example.com:0", "example.com:0"),
        ("my_service:8000", "my_service:8000"),
        ("example.com:443", "example.com"),
        ("example.com:80", "example.com"),
    ],
)
def test_scope_normalizes_default_ports_and_preserves_other_ports(scope, normalized, crawl):
    from archivebox.core.models import Snapshot
    from archivebox.domains.scope import normalize_site_scope, site_snapshots

    assert normalize_site_scope(scope) == normalized
    selected = Snapshot.objects.create(crawl=crawl, url=f"https://{scope}/")
    bare_host = Snapshot.objects.create(crawl=crawl, url=f"https://{scope.split(':')[0]}/")
    expected = {selected.pk, bare_host.pk} if scope != normalized else {selected.pk}
    assert set(site_snapshots(scope).values_list("pk", flat=True)) == expected


def test_domain_cli_rejects_bad_pattern_without_traceback(initialized_archive):
    from archivebox.tests.conftest import run_archivebox_cmd

    result = run_archivebox_cmd(["list", "--filter-type", "domain", "example.com/path"])
    assert result.returncode == 2
    assert "Domain filters accept hostnames" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("identifier", ["-" * 32, "a" * 33, "a-" * 16])
def test_invalid_domain_identifiers_return_not_found(admin_client, identifier):
    response = admin_client.get(f"/admin/domains/{identifier}/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 404


@pytest.mark.parametrize("action", ["export", "delete_selected"])
def test_domain_actions_combine_each_host_and_path_scope(admin_client, crawl, action):
    from archivebox.core.models import Snapshot

    under_prefix = Snapshot.objects.create(crawl=crawl, url="https://example.com/docs/keep")
    other_host = Snapshot.objects.create(crawl=crawl, url="https://other.com/read")
    outside_prefix = Snapshot.objects.create(crawl=crawl, url="https://example.com/outside")
    case_mismatch = Snapshot.objects.create(crawl=crawl, url="https://example.com/Docs/outside")
    filters = {"site_scope": ["example.com/docs", "other.com"]}
    if action == "delete_selected":
        response = admin_client.post(
            "/admin/core/snapshot/",
            {"action": action, "index": "0", "select_across": "1", "_selected_action": [str(under_prefix.pk)]},
            query_params=filters,
            HTTP_HOST=ADMIN_TEST_HOST,
        )
    else:
        response = admin_client.get("/admin/core/snapshot/export.csv", filters, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    if action == "delete_selected":
        assert response.context["title"] == "Confirm snapshot deletion"
        assert {row[0] for row in response.context["preview"]} == {under_prefix.pk, other_host.pk}
    else:
        csv_text = b"".join(response.streaming_content).decode()
        assert under_prefix.url in csv_text and other_host.url in csv_text
        assert outside_prefix.url not in csv_text and case_mismatch.url not in csv_text
    assert not Snapshot.objects.filter(status="deleting").exists()


def test_domain_delete_link_uses_native_confirmation(admin_client, crawl):
    from archivebox.core.models import Snapshot

    selected = Snapshot.objects.create(crawl=crawl, url="https://example.com/delete-confirmation")
    unrelated = Snapshot.objects.create(crawl=crawl, url="https://other.example/keep")
    page = admin_client.get("/admin/domains/", {"table": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    path = next(row["snapshot_url"] for row in page.context["domains"] if row["domain"] == "example.com")
    assert (path + "#delete-snapshots").encode() in page.content
    response = admin_client.post(
        path,
        {"action": "delete_selected", "_selected_action": str(selected.pk), "select_across": "1", "index": "0"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert response.context["title"] == "Confirm snapshot deletion"
    assert selected.url.encode() in response.content
    assert unrelated.url.encode() not in response.content
    assert [row[0] for row in response.context["preview"]] == [selected.pk]
    selected.refresh_from_db()
    unrelated.refresh_from_db()
    assert selected.status != "deleting"
    assert unrelated.status != "deleting"
    newly_captured = Snapshot.objects.create(crawl=crawl, url="https://example.com/after-confirmation")
    confirmed = admin_client.post(
        response.context["confirmation_url"],
        {
            "action": "delete_selected",
            "post": "yes",
            "select_across": "1",
            "_selected_action": [str(selected.pk)],
            "selection": response.context["selection"],
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert confirmed.status_code == 302
    selected.refresh_from_db()
    unrelated.refresh_from_db()
    newly_captured.refresh_from_db()
    assert selected.status == "deleting"
    assert unrelated.status != "deleting"
    assert newly_captured.status != "deleting"


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
    cached.save(update_fields=["config"])
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
