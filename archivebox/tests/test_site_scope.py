# ruff: noqa: F811 - pytest injects the shared real capture fixture by name.
"""Derived site scope selects real persisted snapshots across native crawls."""

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.test_original_domain_replay import saved_site  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def test_site_scope_authority_wildcard_and_prefix_boundaries(crawl):
    from archivebox.core.models import Snapshot
    from archivebox.domains.scope import site_snapshots, site_snapshot_filters
    from archivebox.core.exports import get_export_queryset

    urls = [
        "https://news.ycombinator.com/",
        "http://news.ycombinator.com:80/newest",
        "https://NEWS.YCOMBINATOR.COM:443/docs/intro",
        "https://news.ycombinator.com/docs?lang=en",
        "https://news.ycombinator.com/docstring",
        "https://sub.news.ycombinator.com/docs/intro",
        "https://news.ycombinator.com.evil.example/docs",
        "https://news.ycombinator.com@evil.example/docs",
        "https://other.example/docs",
    ]
    for url in urls:
        Snapshot.objects.create(url=url, crawl=crawl)
    assert set(site_snapshots("news.ycombinator.com").values_list("url", flat=True)) == set(urls[:5])
    assert set(site_snapshots("*.news.ycombinator.com").values_list("url", flat=True)) == set(urls[:6])
    assert set(site_snapshots("https://news.ycombinator.com/docs").values_list("url", flat=True)) == set(urls[2:4])
    assert set(site_snapshots("*.news.ycombinator.com/docs").values_list("url", flat=True)) == {urls[2], urls[3], urls[5]}
    for scope in ["news.ycombinator.com", "*.news.ycombinator.com", "https://news.ycombinator.com/docs", "*.news.ycombinator.com/docs"]:
        assert set(get_export_queryset(site_snapshot_filters(scope), public_only=False).values_list("url", flat=True)) == set(
            site_snapshots(scope).values_list("url", flat=True),
        )


@pytest.mark.parametrize(
    "scope",
    ["https://admin:password@example.com/", "https://example.com/?x=1", "example.com#fragment", "*evil.example", ""],
)
def test_site_scope_rejects_ambiguous_authorities(scope):
    from archivebox.domains.scope import normalize_site_scope

    with pytest.raises(ValueError):
        normalize_site_scope(scope)


def test_derived_site_reads_other_crawls_without_creating_state(admin_client, saved_site):
    from archivebox.crawls.models import Crawl
    from archivebox.domains.scope import crawl_site_scope

    # A new native crawl has no own snapshots. Its saved-site view must show the
    # earlier genuine captures, exactly like the scope-only view with no crawl.
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", label="Later crawl", tags_str="site-clone")
    before = Crawl.objects.count()
    response = admin_client.get(f"/admin/domains/{crawl.pk}/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    page = admin_client.get(response["Location"], HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200
    assert set(page.context["cl"].queryset.values_list("pk", flat=True)) == {snapshot.pk for snapshot, _, _ in saved_site}
    derived = admin_client.get("/admin/domains/site/", {"scope": "news.ycombinator.com"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert derived.status_code == 302
    assert derived["Location"] == response["Location"]
    exports = admin_client.get("/admin/domains/site/export/", {"scope": "news.ycombinator.com"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert exports.status_code == 200
    assert exports["Content-Type"] == "application/json"
    assert exports.json()["count"] == len(saved_site)
    assert exports.json()["query"] == "domain=news.ycombinator.com"
    assert Crawl.objects.count() == before
    assert crawl_site_scope(crawl) == "news.ycombinator.com"


def test_domain_table_uses_native_snapshot_actions_and_links(admin_client, saved_site):
    response = admin_client.get("/admin/domains/", {"o": "-count"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    rows = list(response.context["domains"])
    assert len(rows) == 1
    row = rows[0]
    assert row["domain"] == "ycombinator.com"
    assert row["scope"] == "*.ycombinator.com"
    assert row["snapshot_count"] == len(saved_site)
    for snapshot, _, _ in saved_site:
        snapshot.refresh_from_db(fields=["output_size"])
    assert row["total_size"] == sum(snapshot.output_size for snapshot, _, _ in saved_site)
    assert "domain=%2A.ycombinator.com" in row["snapshot_url"]
    assert "snapshot__domain=%2A.ycombinator.com" in row["persona_url"]
    assert "replay-auth/" in row["replay_url"]
    body = response.content.decode()
    assert 'id="changelist-form"' in body
    assert 'name="_selected_action" value="*.ycombinator.com"' in body
    assert 'value="resnapshot_snapshot"' in body and 'value="delete_selected"' in body
    assert 'value="html_zip"' in body and "MAX 4GB" in body
    assert "Site crawls" not in body
