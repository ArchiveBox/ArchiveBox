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


@pytest.mark.parametrize("descending", [False, True])
def test_domain_page_seeks_past_large_subdomain_groups(admin_user, descending):
    import cProfile
    import pstats

    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    urls = [f"https://site{i:05}.example.com/" for i in range(1001)]
    urls += ["https://example.com/", "https://example-other.com/", "https://other.com/", "https://tenant.github.io/"]
    Snapshot.objects.bulk_create([Snapshot(crawl=crawl, url=url, timestamp=str(1920000000 + i)) for i, url in enumerate(urls)])
    profile = cProfile.Profile()
    with profile:
        first, cursor = Snapshot.objects.all().domain_choices_page("", 2, descending=descending)
        second, cursor = Snapshot.objects.all().domain_choices_page("", 2, cursor, descending=descending)
    assert cursor is None
    assert len(first) == len(second) == 2
    assert set(first) | set(second) == {"example.com", "example-other.com", "other.com", "tenant.github.io"}
    grouped = sum(stats[1] for (_, _, function), stats in pstats.Stats(profile).stats.items() if function == "group_domain_key")
    assert grouped < 20, f"Grouped {grouped} hostnames for four displayed domains"


@pytest.mark.parametrize("descending", [False, True])
def test_domain_page_keeps_nested_public_suffix_groups(admin_user, descending):
    create_pages(
        admin_user,
        [
            "https://amazonaws.com/",
            "https://a.amazonaws.com/",
            "https://b.amazonaws.com/",
            "https://one.s3.amazonaws.com/",
            "https://two.s3.amazonaws.com/",
            "https://z.amazonaws.com/",
        ],
    )
    names = []
    cursor = None
    while True:
        page, cursor = Snapshot.objects.all().domain_choices_page("", 1, cursor, descending=descending)
        names.extend(page)
        if cursor is None:
            break
    assert len(names) == 3
    assert set(names) == {"amazonaws.com", "one.s3.amazonaws.com", "two.s3.amazonaws.com"}


def test_domain_filter_matches_boundaries_and_arbitrary_subdomains(admin_user):
    default_port = [
        "https://example.com/",
        "https://EXAMPLE.COM?query=1",
        "https://example.com:80/path",
        "http://example.com:443/path",
        "http://a.b.c.example.com:80/path",
        "https://a.example.com:443/path",
    ]
    port_8080 = ["http://a.b.c.example.com:8080/path", "https://example.com:8080/path"]
    other_domains = [
        "https://other.com/",
        "https://example.com.evil.test/",
        "https://notexample.com/",
        "https://evil.test/?url=https://example.com/",
        "https://example.com:8180/path",
        "https://notexample.com:8080/path",
    ]
    create_pages(admin_user, default_port + port_8080 + other_domains)
    for scope in ["example.com", "https://example.com:443/", "http://example.com:80/"]:
        assert set(Snapshot.objects.filter(domain=scope).values_list("url", flat=True)) == set(default_port[:4])
    for scope in ["*.example.com", "*.example.com:80", "*.example.com:443"]:
        assert set(Snapshot.objects.filter_by_domain(scope).values_list("url", flat=True)) == set(default_port)
    assert set(Snapshot.objects.all().filter(domain="*.example.com,other.com").values_list("url", flat=True)) == {
        *default_port,
        other_domains[0],
    }
    assert set(Snapshot.objects.filter_by_patterns(["*.example.com"], "domain").values_list("url", flat=True)) == set(default_port)
    assert set(Snapshot.objects.filter_by_domain("*.example.com:8080").values_list("url", flat=True)) == set(port_8080)
    assert list(Snapshot.objects.filter_by_domain("example.com:8080").values_list("url", flat=True)) == [port_8080[1]]


def test_domain_summary_extracts_hosts_and_preserves_nondefault_ports(admin_user):
    urls = [
        "https://reader@example.com/path",
        "https://example.com:80/path",
        "http://a.example.com:443/path",
        "http://www.example.com.:4444/?target=other.com",
        "https://example.com:4444/",
        "https://[2001:db8::1]/path",
        "https://[2001:db8::1]:8443/path",
        "https://198.51.100.5:81/?path=example.com",
        "https://github.io/",
        "https://tenant.github.io/",
        "https://bücher.de/",
        "https://xn--bcher-kva.de/",
        "https://BÜCHER.DE:443/",
    ]
    create_pages(admin_user, urls)
    rows = {row["domain"]: row for row in Snapshot.objects.domain_summary()}
    assert set(rows) == {
        "example.com",
        "example.com:4444",
        "2001:db8::1",
        "[2001:db8::1]:8443",
        "198.51.100.5:81",
        "github.io",
        "tenant.github.io",
        "xn--bcher-kva.de",
    }
    assert rows["example.com"]["snapshot_count"] == 3
    assert rows["example.com:4444"]["scope"] == "*.example.com:4444"
    assert rows["example.com:4444"]["snapshot_count"] == 2
    assert rows["2001:db8::1"]["scope"] == "[2001:db8::1]"
    assert rows["[2001:db8::1]:8443"]["scope"] == "[2001:db8::1]:8443"
    for row in rows.values():
        assert Snapshot.objects.filter_by_domain(row["scope"]).count() == row["snapshot_count"]


@pytest.mark.parametrize("domain", ["example.com/path", "https://user@example.com/", "ftp://example.com/", "example.com?target=other.com"])
def test_invalid_domain_filter_is_not_a_broader_query(domain):
    with pytest.raises(ValueError):
        Snapshot.objects.filter_by_domain(domain)


def test_snapshot_domain_key_follows_url_writes(admin_user):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://maps.google.co.uk/")
    page = Snapshot.objects.bulk_create([Snapshot(crawl=crawl, url="https://maps.google.co.uk:8080/search")])[0]
    rows = Snapshot.objects.filter(pk=page.pk)

    assert rows.values_list("reversed_domain", flat=True).get() == "8080:uk.co.google.maps"
    assert rows.filter(domain="*.google.co.uk:8080").exists()

    assert rows.update(url="https://www.google.co.uk:80/") == 1
    assert rows.values_list("reversed_domain", flat=True).get() == "uk.co.google.www"
    assert rows.filter(domain="*.google.co.uk").exists()
    assert not rows.filter(domain="*.google.co.uk:8080").exists()

    page.url = "http://example.org:443/search"
    assert Snapshot.objects.bulk_update([page], ["url"]) == 1
    assert rows.values_list("reversed_domain", flat=True).get() == "org.example"
    assert rows.filter(domain="example.org").exists()
    assert not rows.filter(domain="*.google.co.uk").exists()

    page.url = "https://other.example.org:8443/"
    page.save(update_fields=["url"])
    assert rows.values_list("reversed_domain", flat=True).get() == "8443:org.example.other"
    assert rows.filter(domain="*.example.org:8443").exists()
    assert not rows.filter(domain="example.org").exists()


def test_domain_summary_groups_psl_parents_without_loading_snapshot_rows(admin_user):
    one = Persona.objects.create(name="Domain first", created_by=admin_user)
    two = Persona.objects.create(name="Domain second", created_by=admin_user)
    pages = create_pages(admin_user, ["https://example.co.uk/", "https://a.b.example.co.uk/"], persona=one)
    pages += create_pages(admin_user, ["http://other.example.co.uk:80/", "https://other.com/"], persona=two)
    pages += create_pages(admin_user, ["https://one.github.io/", "https://two.github.io/"])
    origin = timezone.now() - timedelta(days=10)
    for index, page in enumerate(pages):
        Snapshot.objects.filter(pk=page.pk).update(output_size=(index + 1) * 100, created_at=origin + timedelta(days=index))
    with CaptureQueriesContext(connection) as queries:
        rows = {row["domain"]: row for row in Snapshot.objects.domain_summary()}
    assert len(queries) == 1
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


def test_domain_counts_are_exact_on_first_page_and_after_writes(admin_client, admin_user):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://claude.ai/")
    pages = Snapshot.objects.bulk_create(
        [
            Snapshot(crawl=crawl, url=f"https://{'chat.' if index % 2 else ''}claude.ai/{index}", timestamp=str(1920000000 + index))
            for index in range(79)
        ],
    )
    create_pages(admin_user, ["https://notclaude.ai/", "https://claude.ai.evil.test/", "https://claude.ai:8080/"])

    def check(expected):
        domains = admin_client.get("/admin/domains/", {"table": "1", "q": "claude.ai"}, HTTP_HOST=ADMIN_TEST_HOST)
        assert domains.status_code == 200
        row = next(row for row in domains.context["domains"] if row["domain"] == "claude.ai")
        assert row["snapshot_count"] == expected
        assert f">{expected}</a></td>" in domains.content.decode()
        for page_number in (1, 2):
            with CaptureQueriesContext(connection) as queries:
                response = admin_client.get(
                    "/admin/core/snapshot/",
                    {"domain": "*.claude.ai", "p": page_number},
                    HTTP_HOST=ADMIN_TEST_HOST,
                )
            assert response.status_code == 200
            cl = response.context["cl"]
            assert cl.result_count_exact and not cl.result_count_cached
            assert cl.display_result_count == cl.result_count == cl.paginator.count == expected
            assert len(cl.result_list) == (50 if page_number == 1 else expected - 50)
            count_sql = [query["sql"] for query in queries if "COUNT(*)" in query["sql"] and '"reversed_domain"' in query["sql"]]
            assert len(count_sql) == 1
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("EXPLAIN QUERY PLAN " + count_sql[0])
                    plan = " ".join(str(row[-1]) for row in cursor.fetchall())
                assert "snapshot_reversed_domain_idx" in plan, plan
                assert "SCAN core_snapshot" not in plan, plan

    check(79)
    Snapshot.objects.filter(pk=pages[-1].pk).update(url="https://other.example/")
    check(78)
    Snapshot.objects.filter(pk=pages[-2].pk).delete()
    check(77)
    Snapshot.objects.filter(pk__in=[page.pk for page in pages[:60]]).update(status=Snapshot.StatusChoices.SEALED)
    response = admin_client.get(
        "/admin/core/snapshot/",
        {"domain": "*.claude.ai", "status__exact": "sealed"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert response.context["cl"].display_result_count == 60
    assert response.context["cl"].result_count_exact


def test_domain_name_opens_root_capture_and_count_opens_filtered_list(admin_client, admin_user):
    from html.parser import HTMLParser
    from archivebox.core.routes_util import build_snapshot_detail_url

    pages = create_pages(admin_user, ["https://example.com/", "http://deep.sub.example.com/article", "https://other.com/"])
    pages[0].config = {"PERMISSIONS": "private"}
    pages[0].save(update_fields=["config"])
    response = admin_client.get("/admin/domains/", {"table": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
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
    pages = create_pages(
        api_admin_user,
        [
            "https://example.com/",
            "https://deep.sub.example.com:80/",
            "https://deep.sub.example.com:8080/",
            "https://example.com.evil.test/",
        ],
    )
    for scope, expected in [("*.example.com", pages[:2]), ("*.example.com:8080", pages[2:3])]:
        response = client.get("/api/v1/core/snapshots", {"domain": scope}, **api_headers)
        assert response.status_code == 200, response.content
        assert response.json()["count"] == len(expected)
        assert {item["id"].replace("-", "") for item in response.json()["items"]} == {str(page.pk).replace("-", "") for page in expected}


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
    assert len(queries) == 1
    assert len(rows) == 1
    assert rows[0]["root_id"] == pages[expected].pk
    assert rows[0]["oldest_id"] == pages[0].pk
    assert rows[0]["newest_id"] == pages[-1].pk
    # A filtered summary must not choose a homepage outside its source queryset.
    assert Snapshot.objects.filter(pk=pages[-1].pk).domain_summary()[0]["root_id"] == pages[-1].pk


def test_domain_summary_batches_metadata_and_preserves_ties(admin_user):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    pages = Snapshot.objects.bulk_create(
        [
            Snapshot(crawl=crawl, url=f"https://example.com/{index}", timestamp=str(1900000000 + index), output_size=index)
            for index in range(1001)
        ],
    )
    created = timezone.now()
    Snapshot.objects.filter(crawl=crawl).update(created_at=created)
    with CaptureQueriesContext(connection) as queries:
        rows = Snapshot.objects.filter(crawl=crawl).domain_summary()
    assert len(queries) == 2
    assert len(rows) == 1
    row = rows[0]
    assert row["snapshot_count"] == 1001
    assert row["total_size"] == sum(range(1001))
    assert row["oldest_id"] == min(page.pk for page in pages)
    assert row["newest_id"] == row["root_id"] == max(page.pk for page in pages)
    # Full capture configuration and output inventories do not belong in a
    # domain tally, regardless of collection size.
    assert all('"config"' not in query["sql"] and '"output_files"' not in query["sql"] for query in queries)


@pytest.mark.parametrize("legacy_output", [False, True])
def test_domain_size_sort_reuses_metadata_and_only_loads_favicons(admin_client, admin_user, legacy_output):
    from archivebox.core.models import ArchiveResult

    pages = create_pages(admin_user, ["https://large.example/", "https://small.example/"])
    for page, size in zip(pages, (9000, 10), strict=True):
        ArchiveResult.objects.create(
            snapshot=page,
            plugin="dom",
            status="succeeded",
            output_files={"dom/output.html": {"size": size}},
            output_size=size,
        )
    ArchiveResult.objects.create(
        snapshot=pages[0],
        plugin="favicon",
        status="succeeded",
        output_str="favicon.ico",
        output_files={} if legacy_output else {"favicon/favicon.ico": {"size": 12}},
        output_json={"unused": "x" * 10000},
        notes="Not needed for the favicon",
        output_size=12,
    )
    response = admin_client.get("/admin/domains/", {"o": "size", "table": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [row["domain"] for row in response.context["domains"]] == ["small.example", "large.example"]
    assert b"favicon/favicon.ico" in response.content
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get("/admin/domains/", {"o": "-size", "table": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [row["domain"] for row in response.context["domains"]] == ["large.example", "small.example"]
    assert b"favicon/favicon.ico" in response.content
    assert not any('AS "crawl__persona_id"' in query["sql"] for query in queries)
    output_queries = [query["sql"] for query in queries if 'FROM "core_archiveresult"' in query["sql"]]
    assert len(output_queries) == 1
    assert '"core_archiveresult"."plugin" IN' in output_queries[0]
    assert "'favicon'" in output_queries[0] and "'dom'" not in output_queries[0]
    assert all(f'"core_archiveresult"."{field}"' not in output_queries[0] for field in ("output_json", "notes", "process_id"))
    # Cached totals do not turn a concurrently removed capture into a 500.
    Snapshot.objects.filter(pk=pages[0].pk).delete()
    response = admin_client.get("/admin/domains/", {"o": "size", "table": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [row["domain"] for row in response.context["domains"]] == ["small.example"]


def test_domain_metadata_is_reused_across_administrators(admin_client, admin_user):
    from django.contrib.auth import get_user_model

    create_pages(admin_user, ["https://shared.example/", "https://shared.example/article"])
    first = admin_client.get("/admin/domains/", {"o": "count", "table": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert first.status_code == 200
    assert [(row["domain"], row["snapshot_count"]) for row in first.context["domains"]] == [("shared.example", 2)]

    other = get_user_model().objects.create_superuser(username="other_domain_admin", password="testpassword")
    admin_client.force_login(other)
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get("/admin/domains/", {"o": "-count", "table": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [(row["domain"], row["snapshot_count"]) for row in response.context["domains"]] == [("shared.example", 2)]
    assert not any('AS "crawl__persona_id"' in query["sql"] for query in queries)

    other.is_superuser = False
    other.save(update_fields=["is_superuser"])
    for params in ({}, {"o": "count", "table": "1"}):
        response = admin_client.get("/admin/domains/", params, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 403


def test_stale_domain_metadata_refresh_does_not_block_page(admin_client, admin_user):
    from threading import enumerate as threads
    from django.core.cache import cache
    from archivebox.config import CONSTANTS

    create_pages(admin_user, ["https://shared.example/"])
    stats = {"o": "count", "table": "1"}
    response = admin_client.get("/admin/domains/", stats, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    key = f"domain-summary:{CONSTANTS.COLLECTION_ID}"
    assert cache.touch(key, timeout=3600)
    create_pages(admin_user, ["https://shared.example/article"])
    cache.delete(f"{key}:refresh")
    for thread in threads():
        if thread.name in {"collection-summary", "snapshot-list-count"}:
            thread.join(timeout=10)
            assert not thread.is_alive()
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get("/admin/domains/", stats, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.context["domains"][0]["snapshot_count"] == 2
    assert not any('AS "crawl__persona_id"' in query["sql"] for query in queries)
    for thread in threads():
        if thread.name == "domain-summary":
            thread.join(timeout=10)
            assert not thread.is_alive()
    response = admin_client.get("/admin/domains/", stats, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.context["domains"][0]["snapshot_count"] == 2


def test_domain_cache_refresh_error_releases_statistics_lock(admin_user, tmp_path):
    from pathlib import Path

    from django.core.cache import cache, caches
    from django.test import override_settings

    from archivebox.config import CONSTANTS
    from archivebox.domains.views import _domain_rows
    from archivebox.progressmonitor.collection import _refresh_lock

    create_pages(admin_user, ["https://shared.example/"])
    with override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache", "LOCATION": str(tmp_path)}},
    ):
        expected = _domain_rows()
        assert expected[0]["snapshot_count"] == 1
        refresh_key = f"domain-summary:{CONSTANTS.COLLECTION_ID}:refresh"
        cache.delete(refresh_key)
        # A real malformed cache entry makes FileBasedCache.add fail while the
        # previously cached summary remains readable, including when run as root.
        Path(caches["default"]._key_to_file(refresh_key)).mkdir()
        assert not _refresh_lock.locked()
        try:
            with CaptureQueriesContext(connection) as queries:
                assert _domain_rows() == expected
            assert not queries
            assert _refresh_lock.acquire(blocking=False)
        finally:
            if _refresh_lock.locked():
                _refresh_lock.release()


def test_domain_summary_later_pages_seek_id_range(admin_user):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    pages = Snapshot.objects.bulk_create(
        [Snapshot(crawl=crawl, url=f"https://example.com/{index}", timestamp=str(1900600000 + index)) for index in range(1001)],
    )
    with CaptureQueriesContext(connection) as queries:
        rows = Snapshot.objects.domain_summary()
    assert len(rows) == 1 and rows[0]["snapshot_count"] == len(pages)
    assert len(queries) == 2
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            # Give the planner real cardinalities for the freshly inserted rows.
            cursor.execute("ANALYZE core_snapshot")
            cursor.execute("ANALYZE crawls_crawl")
        explain = "EXPLAIN QUERY PLAN " if connection.vendor == "sqlite" else "EXPLAIN "
        cursor.execute(explain + queries[1]["sql"])
        plan = " ".join(str(row[-1]) for row in cursor.fetchall())
    if connection.vendor == "sqlite":
        assert "(id>?)" in plan, plan
        assert "IN-OPERATOR" not in plan, plan
    else:
        assert "Index Cond: (id >" in plan, plan
        assert "SubPlan" not in plan, plan


def test_domain_summary_deduplicates_filtered_tag_joins(admin_user):
    from archivebox.core.models import SnapshotTag, Tag

    pages = create_pages(admin_user, ["https://example.com/one", "https://example.com/two", "https://other.com/"])
    tags = [Tag.objects.create(name=f"Domain summary {index}") for index in range(2)]
    SnapshotTag.objects.bulk_create([SnapshotTag(snapshot=page, tag=tag) for page in pages[:2] for tag in tags])
    rows = Snapshot.objects.filter(tags__in=tags).domain_summary()
    assert len(rows) == 1
    assert rows[0]["domain"] == "example.com"
    assert rows[0]["snapshot_count"] == 2
