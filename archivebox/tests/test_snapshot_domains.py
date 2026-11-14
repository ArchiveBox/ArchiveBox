"""Domain views are ordinary, correctly bounded snapshot queries."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def create_pages(user, urls, *, persona=None):
    crawl = Crawl.objects.create(created_by=user, urls="\n".join(urls), persona=persona)
    return [Snapshot.objects.create(crawl=crawl, url=url) for url in urls]


def test_domain_filter_matches_boundaries_and_arbitrary_subdomains(admin_user):
    urls = [
        "https://example.com/",
        "http://a.b.c.example.com:8080/path",
        "https://EXAMPLE.COM?query=1",
        "https://other.com/",
        "https://example.com.evil.test/",
        "https://notexample.com/",
        "https://evil.test/?url=https://example.com/",
    ]
    create_pages(admin_user, urls)
    assert set(Snapshot.objects.filter_by_domain("*.example.com").values_list("url", flat=True)) == set(urls[:3])
    assert set(Snapshot.objects.filter(domain="example.com").values_list("url", flat=True)) == {urls[0], urls[2]}
    assert Snapshot.objects.all().filter(domain="*.example.com,other.com").count() == 4
    assert Snapshot.objects.filter_by_patterns(["*.example.com"], "domain").count() == 3
    assert Snapshot.objects.filter_by_domain("*.example.com:8080").count() == 1


def test_domain_summary_extracts_hosts_without_ports_userinfo_or_query(admin_user):
    urls = [
        "https://reader@example.com/path",
        "http://www.example.com.:4444/?target=other.com",
        "https://[2001:db8::1]:8443/path",
        "https://198.51.100.5:81/?path=example.com",
        "https://github.io/",
        "https://tenant.github.io/",
        "https://bücher.de/",
        "https://xn--bcher-kva.de/",
    ]
    create_pages(admin_user, urls)
    rows = {row["domain"]: row for row in Snapshot.objects.domain_summary()}
    assert set(rows) == {"example.com", "2001:db8::1", "198.51.100.5", "github.io", "tenant.github.io", "xn--bcher-kva.de"}
    assert rows["example.com"]["snapshot_count"] == 2
    assert rows["2001:db8::1"]["scope"] == "[2001:db8::1]"
    for row in rows.values():
        assert Snapshot.objects.filter_by_domain(row["scope"]).count() == row["snapshot_count"]


@pytest.mark.parametrize("domain", ["example.com/path", "https://user@example.com/", "ftp://example.com/", "example.com?target=other.com"])
def test_invalid_domain_filter_is_not_a_broader_query(domain):
    with pytest.raises(ValueError):
        Snapshot.objects.filter_by_domain(domain)


def test_domain_summary_groups_psl_parents_without_loading_snapshot_rows(admin_user):
    one = Persona.objects.create(name="Domain first", created_by=admin_user)
    two = Persona.objects.create(name="Domain second", created_by=admin_user)
    pages = create_pages(admin_user, ["https://example.co.uk/", "https://a.b.example.co.uk/"], persona=one)
    pages += create_pages(admin_user, ["http://other.example.co.uk:8080/", "https://other.com/"], persona=two)
    pages += create_pages(admin_user, ["https://one.github.io/", "https://two.github.io/"])
    origin = timezone.now() - timedelta(days=10)
    for index, page in enumerate(pages):
        Snapshot.objects.filter(pk=page.pk).update(output_size=(index + 1) * 100, created_at=origin + timedelta(days=index))
    with CaptureQueriesContext(connection) as queries:
        rows = {row["domain"]: row for row in Snapshot.objects.domain_summary()}
    assert len(queries) == 3
    assert set(rows) == {"example.co.uk", "other.com", "one.github.io", "two.github.io"}
    row = rows["example.co.uk"]
    assert row["scope"] == "*.example.co.uk"
    assert (row["snapshot_count"], row["total_size"], row["persona_count"]) == (3, 600, 2)
    assert (row["oldest_id"], row["newest_id"]) == (pages[0].pk, pages[2].pk)
    assert row["oldest_at"] == origin
    assert row["newest_at"] == origin + timedelta(days=2)
    assert Snapshot.objects.filter(pk=pages[0].pk).domain_summary()[0]["snapshot_count"] == 1


def test_native_snapshot_and_persona_admin_domain_filters(admin_client, admin_user):
    included = Persona.objects.create(name="Included domain", created_by=admin_user)
    excluded = Persona.objects.create(name="Excluded domain", created_by=admin_user)
    pages = create_pages(admin_user, ["https://a.b.example.com/"], persona=included)
    create_pages(admin_user, ["https://example.com.evil.test/"], persona=excluded)
    snapshots = admin_client.get("/admin/core/snapshot/", {"domain": "*.example.com"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert snapshots.status_code == 200
    assert list(snapshots.context["cl"].queryset.values_list("pk", flat=True)) == [pages[0].pk]
    personas = admin_client.get("/admin/personas/persona/", {"snapshot__domain": "*.example.com"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert personas.status_code == 200
    assert list(personas.context["cl"].queryset.values_list("pk", flat=True)) == [included.pk]


def test_domain_name_opens_root_capture_and_count_opens_filtered_list(admin_client, admin_user):
    from html.parser import HTMLParser
    from archivebox.core.routes_util import build_snapshot_detail_url

    pages = create_pages(admin_user, ["https://example.com/", "http://deep.sub.example.com/article", "https://other.com/"])
    pages[0].config = {"PERMISSIONS": "private"}
    pages[0].save(update_fields=["config"])
    response = admin_client.get("/admin/domains/", HTTP_HOST=ADMIN_TEST_HOST)
    row = next(row for row in response.context["domains"] if row["domain"] == "example.com")

    class DomainLinks(HTMLParser):
        in_domain = False
        links = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "th":
                self.in_domain = attrs.get("class") == "field-domain"
            if tag == "a" and self.in_domain:
                self.links.append(attrs["href"])

        def handle_endtag(self, tag):
            if tag == "th":
                self.in_domain = False

    parser = DomainLinks()
    parser.feed(response.content.decode())
    assert (
        row["domain_url"] == build_snapshot_detail_url(pages[0].archive_path_from_db, request=response.wsgi_request) + "?header=collapsed"
    )
    assert row["domain_url"] in parser.links
    assert row["snapshot_url"] not in parser.links
    snapshots = admin_client.get(row["snapshot_url"], HTTP_HOST=ADMIN_TEST_HOST)
    assert snapshots.status_code == 200
    assert set(snapshots.context["cl"].queryset.values_list("pk", flat=True)) == {page.pk for page in pages[:2]}
    legacy = admin_client.get("/admin/domains/site/?scope=example.com", HTTP_HOST=ADMIN_TEST_HOST)
    assert legacy.status_code == 302
    assert legacy["Location"] == row["snapshot_url"]


def test_snapshot_api_domain_filter(client, api_admin_user, api_headers):
    pages = create_pages(api_admin_user, ["https://example.com/", "https://deep.sub.example.com/", "https://example.com.evil.test/"])
    response = client.get("/api/v1/core/snapshots", {"domain": "*.example.com"}, **api_headers)
    assert response.status_code == 200, response.content
    assert response.json()["count"] == 2
    assert {item["id"].replace("-", "") for item in response.json()["items"]} == {str(page.pk).replace("-", "") for page in pages[:2]}


@pytest.mark.parametrize(
    ("urls", "expected"),
    [
        (["https://example.com/", "https://example.com/news/article"], 0),
        (["https://example.com/news", "https://example.com/news/article"], 0),
        (["https://example.com/news/", "https://example.com/latest"], 1),
        (["https://example.com/?next=/one/two", "https://example.com/news#part/one/two"], 0),
        (["https://example.com?next=/one/two", "https://example.com/news"], 0),
        (["https://example.com/news", "https://sub.example.com/", "https://other.example.com/latest"], 1),
        (["https://example.com/", "https://sub.example.com/"], 1),
    ],
)
def test_domain_summary_selects_nearest_root_then_newest(admin_user, urls, expected):
    pages = create_pages(admin_user, urls)
    origin = timezone.now() - timedelta(days=len(pages))
    for index, page in enumerate(pages):
        Snapshot.objects.filter(pk=page.pk).update(created_at=origin + timedelta(days=index))
    with CaptureQueriesContext(connection) as queries:
        rows = Snapshot.objects.domain_summary()
    assert len(queries) == 3
    assert len(rows) == 1
    assert rows[0]["root_id"] == pages[expected].pk
    assert rows[0]["oldest_id"] == pages[0].pk
    assert rows[0]["newest_id"] == pages[-1].pk
    # A filtered summary must not choose a homepage outside its source queryset.
    assert Snapshot.objects.filter(pk=pages[-1].pk).domain_summary()[0]["root_id"] == pages[-1].pk
