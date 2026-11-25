"""Query semantics at the ORM, CLI, HTTP and permission boundaries."""

import json
from datetime import UTC, datetime
from itertools import permutations
from urllib.parse import urlencode

import pytest
from django.urls import reverse

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.search.interpreter import SnapshotSearch
from archivebox.search.language import Term, parse
from archivebox.tests.conftest import WEB_TEST_HOST, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db
from archivebox.tests.test_search import consume_streaming_response

pytestmark = pytest.mark.django_db(transaction=True)


def test_operator_membership(crawl):
    stamp = datetime(2026, 12, 31, 16, 30, tzinfo=UTC)
    row = Snapshot.objects.create(
        crawl=crawl,
        url="https://solarcity.com/panel",
        title="Solar ABC:DEF report",
        bookmarked_at=stamp,
        status="sealed",
        config={"PERMISSIONS": "public", "description": {"scope": ["LabNote"]}},
    )
    other = Snapshot.objects.create(crawl=crawl, url="https://elsewhere.example/o", title="Solar weekly report")
    row.save_tags(["ABC:DEF", "abc-xyz", "green choice"])
    ArchiveResult.objects.create(snapshot=row, plugin="solar_reader", status="succeeded", output_files={"figure.PDF": {"size": 82}})
    ArchiveResult.objects.create(snapshot=other, plugin="solar_reader", status="failed", output_files={"x.txt": {}})
    scope = Snapshot.objects.filter(pk__in=[row.pk, other.pk])
    for query in (
        'tag:"ABC:DEF" tags:abc,"green choice"',
        'title:"abc:def" AND ~title:weekly',
        "site:SOLARCITY.COM (after:2026 before:2027) bookmarked:2026-12-31",
        "filetype:png,pdf plugins:reader",
        f'permissions:public status:sealed owner:"{crawl.created_by.username}" site:solarcity.com',
        'tags:missing OR (meta:"LabNote" AND ~plugins:other)',
        'title:missing OR tags:abc title:"ABC:DEF"',
    ):
        search = SnapshotSearch(scope, query)
        assert list(search.stream()) == [row.pk], query
        assert not search.partial
    for query in ("tags:Abc", 'title:"Abc:Def"', "filetype:PdF", "meta:LabNOTE", "before:2026 site:solarcity.com"):
        assert not SnapshotSearch(scope, query).queryset().exists(), query
    assert parse('"ABC:DEF"') == Term("literal", "ABC:DEF")
    assert parse('tags:"ABC:DEF"') == Term("tags", "ABC:DEF")
    assert parse(r'tags:"a,b","say \"yes\""') == Term("tags", 'a,b,say "yes"', ("a,b", 'say "yes"'))
    with pytest.raises(ValueError, match="Invalid quoted text"):
        parse('title:"unfinished')
    assert not SnapshotSearch(scope, "meta:LabNote", public=True).queryset().exists()


def test_domain_substrings_match_authorities_in_display_order(crawl):
    urls = [
        "https://NEWS.YCombinator.com/item",
        "https://combinator.net/",
        "https://com.ycombinator.news/",
        "https://ycombinator.com:8443/",
        "https://[2001:db8::1]:8080/",
        "https://ycombinator.com@lobste.rs/s/ycombinator.com?domain=ycombinator.com",
        "https://bücher.de/",
        "https://xn--bcher-kva.de/",
    ]
    rows = [Snapshot.objects.create(crawl=crawl, url=url) for url in urls]
    scope = Snapshot.objects.filter(pk__in=[row.pk for row in rows])
    for expr, indices in (
        ("domain:BINATOR", [0, 1, 2, 3]),
        ("site:s.ycomb", [0]),
        ("domain:tor.co", [0, 3]),
        ("domain:com:84", [3]),
        ("domain:db8::1", [4]),
        ("domain:*.ycombinator.com", [0]),
        ("domain:*.ycombinator.com,db8", [0, 4]),
        ("domain:tor.co,db8", [0, 3, 4]),
        ("domain:BÜCHER.DE", [6, 7]),
        ("domain:bÜch", [6, 7]),
        ("domain:XN--BCH", [6, 7]),
        ("domain:news.ycombinator.com:443", []),
        ('domain:"https://news.ycombinator.com/"', []),
        ("domain__exact:ycombinator.com", []),
        ("~(domain:binator OR domain:db8)", [5, 6, 7]),
    ):
        search = SnapshotSearch(scope, expr)
        expected = {rows[i].pk for i in indices}
        assert set(search.queryset().values_list("pk", flat=True)) == expected, expr
        assert set(search.stream()) == expected, expr
    assert not scope.filter(domain="ycombinator.com").exists()


def test_tag_stream_prefers_exact_csv_matches_and_retains_substring_matches(crawl):
    exact = Snapshot.objects.create(crawl=crawl, url="https://lobste.rs/s/exact")
    overlap = Snapshot.objects.create(crawl=crawl, url="https://lobste.rs/s/overlap")
    excluded = Snapshot.objects.create(crawl=crawl, url="https://lobste.rs/s/excluded")
    untagged = Snapshot.objects.create(crawl=crawl, url="https://lobste.rs/s/untagged")
    exact.save_tags(["web,notes", "research", "web,notes archive"])
    overlap.save_tags(["web,notes archive", "research notes", "Research Edition"])
    excluded.save_tags(["web", "notes", "Research Edition"])
    query = 'tags:"web,notes",research'
    scope = Snapshot.objects.filter(pk__in=[exact.pk, overlap.pk, excluded.pk, untagged.pk])
    search = SnapshotSearch(scope, query, streaming=True)
    assert list(search.witnesses(search.indexed_bounds[0])) == [exact.pk]
    assert list(search.stream()) == [exact.pk, overlap.pk]
    assert search.sql_queryset(ranked=True) is not None
    assert set(SnapshotSearch(scope, query).queryset().values_list("pk", flat=True)) == {exact.pk, overlap.pk}

    ordered = scope.order_by("-created_at", "-pk")
    assert list(SnapshotSearch(ordered, query, streaming=True).stream()) == [overlap.pk, exact.pk]
    assert set(SnapshotSearch(scope, f"({query} AND ~tags:Research) OR url:untagged").stream()) == {exact.pk, untagged.pk}
    assert set(SnapshotSearch(scope, f"~({query})").stream()) == {excluded.pk, untagged.pk}
    assert not SnapshotSearch(scope, "tags:missing").queryset().exists()
    assert set(SnapshotSearch(scope, 'tags__name__icontains:"WEB,NOTES"').stream()) == {exact.pk, overlap.pk}
    assert list(SnapshotSearch(scope, 'tags__name__exact:"web,notes" AND ~tags:Research').stream()) == [exact.pk]


def test_filetype_matches_literal_substrings_of_the_final_extension(crawl):
    report = Snapshot.objects.create(crawl=crawl, url="https://arxiv.org/pdf/1706.03762")
    other = Snapshot.objects.create(crawl=crawl, url="https://arxiv.org/abs/1706.03762")
    ArchiveResult.objects.create(snapshot=report, plugin="wget", output_files={"paper/report.PDF": {}, "main.c++": {}})
    ArchiveResult.objects.create(snapshot=other, plugin="wget", output_files={"paper.pdf/index": {}, "report.pdf.html": {}})
    scope = Snapshot.objects.filter(pk__in=[report.pk, other.pk])
    for query in ("filetype:df", "filetype:zip,DF", 'filetype:"++"'):
        assert list(SnapshotSearch(scope, query).stream()) == [report.pk], query
    for query in ("filetype:Df", 'filetype:"%"', 'filetype:"."'):
        assert not SnapshotSearch(scope, query).queryset().exists(), query


def test_nested_sql_predicates_keep_membership_across_operand_orders(crawl):
    match = Snapshot.objects.create(
        crawl=crawl,
        url="https://sqlite.org/optoverview.html",
        title="Query planner",
        config={"guide": "manual"},
    )
    other = Snapshot.objects.create(crawl=crawl, url="https://lucene.apache.org/core/", title="Iterator API")
    match.save_tags(["database"])
    ArchiveResult.objects.create(snapshot=match, plugin="wget", status="succeeded", output_files={"manual.html": {}})
    scope = Snapshot.objects.filter(pk__in=[match.pk, other.pk]).order_by("pk")
    terms = ("meta:manual", "filetype:html", "tags:data", "title:query", "after:2000")

    for a, b, c, d, e in list(permutations(terms))[::11]:
        # Re-parenthesizing the same conjunction must still allow the scalar
        # date comparison to short-circuit the correlated manifest lookup.
        conjunction = f"({a} AND ({b} AND {c})) AND ({d} AND {e})"
        search = SnapshotSearch(scope, conjunction)
        ids = search.sql_queryset().values_list("pk", flat=True)
        assert list(ids) == [match.pk]
        sql, _ = ids.query.sql_with_params()
        assert sql.index("bookmarked_at") < sql.index("core_archiveresult")
        complement = SnapshotSearch(scope, f"~(({conjunction}) OR domain:sqlite.org)")
        assert list(complement.stream()) == [other.pk]


def test_public_search_scope_completion_and_invalid_query(client, crawl):
    from archivebox.machine.models import Machine

    Machine.from_json({"config": {"PUBLIC_INDEX": True}})
    visible = Snapshot.objects.create(crawl=crawl, url="https://solarcity.com/public", title="Study", config={"PERMISSIONS": "public"})
    private = Snapshot.objects.create(crawl=crawl, url="https://solarcity.com/private", title="Study", config={"PERMISSIONS": "private"})
    visible.save_tags(["solar-public"])
    private.save_tags(["solar-private"])
    suggestions = client.get(reverse("search-suggestions"), {"operator": "tags", "prefix": "solar"}, HTTP_HOST=WEB_TEST_HOST)
    assert suggestions.json()["values"] == ["solar-public"]
    for key in ("site", "domain"):
        response = client.get(reverse("search-suggestions"), {"operator": key, "prefix": "SOLAR"}, HTTP_HOST=WEB_TEST_HOST)
        assert response.json()["values"] == ["solarcity.com"]
    params = {"q": "title:study", "tag": str(visible.tags.get().pk)}
    path = reverse("public-index")
    result = client.get(
        reverse("public-search-stream"),
        {**params, "search_url": path + "?" + urlencode(params)},
        HTTP_HOST=WEB_TEST_HOST,
        headers={"X-ArchiveBox-Search-Page": "first"},
    )
    assert consume_streaming_response(result).splitlines()[-1].strip() == b"1"
    page = client.get(path, params, HTTP_HOST=WEB_TEST_HOST, headers={"X-ArchiveBox-Search-Page": result["X-ArchiveBox-Search-Page"]})
    assert [r.pk for r in page.context["object_list"]] == [visible.pk]
    for query in ('tags:"broken', "config__has_key:secret"):
        result = client.get(reverse("public-search-stream"), {"q": query}, HTTP_HOST=WEB_TEST_HOST)
        assert result.status_code == 400


def test_rest_search_and_validation(client, api_headers, crawl):
    snap = Snapshot.objects.create(crawl=crawl, url="https://solarcity.com/a", title="Solar Panel Field Guide")
    snap.save_tags(["solar-2026"])
    Snapshot.objects.create(crawl=crawl, url="https://solarcity.com/b", title="Atlas")
    url = "/api/v1/core/snapshots"
    res = client.get(url, {"search": 'tag:solar site:solarcity.com (title:"Solar Panel" OR title:missing)'}, **api_headers)
    assert res.status_code == 200, res.content
    assert [item["id"].replace("-", "") for item in res.json()["items"]] == [snap.pk.hex]
    unresolved = client.get(url, {"search": 'domain:solarcity.com deep:"unavailable artifact"'}, **api_headers)
    assert unresolved.status_code == 200, unresolved.content
    assert unresolved["X-ArchiveBox-Search-Partial"] == "1"
    assert unresolved.json()["items"] == []
    assert client.get(url, {"search": "(site:solarcity.com"}, **api_headers).status_code == 400


def test_cli_query_and_explicit_sort(initialized_archive):
    from django.contrib.auth import get_user_model
    from archivebox.crawls.models import Crawl

    with use_archivebox_db(initialized_archive):
        owner = get_user_model().objects.create_user(username="operator-cli")
        crawl = Crawl.objects.create(urls="https://solarcity.com/", created_by=owner)
        for title in ["Atlas", "Panels"]:
            snap = Snapshot.objects.create(crawl=crawl, url="https://solarcity.com/" + title, title=title)
            snap.save_tags(["solar-study"])
        Snapshot.objects.create(crawl=crawl, url="https://other.example", title="Panels")
    for cmd in ["list", "search"]:
        result = run_archivebox_cmd(
            [cmd, "tag:solar AND (title:Atlas OR title:Panels)", "--sort", "-title", "--json"],
            cwd=initialized_archive,
        )
        assert result.returncode == 0, result.stderr
        assert [obj["title"] for obj in json.loads(result.stdout)] == ["Panels", "Atlas"]


def test_folder_search_uses_tree_membership_and_public_picker(client, crawl):
    from django.core.exceptions import ValidationError
    from archivebox.core.models import Folder
    from archivebox.core.smart_folders import RuleQuery
    from archivebox.machine.models import Machine

    Machine.from_json({"config": {"PUBLIC_INDEX": True}})
    parent = Folder.objects.create(name="Papers")
    child = Folder.objects.create(name="Some folder name", parent=parent)
    hidden = Folder.objects.create(name="Private research")
    row = Snapshot.objects.create(
        crawl=crawl,
        folder=child,
        title="Study",
        url="https://example.org/paper",
        config={"PERMISSIONS": "public"},
    )
    Snapshot.objects.create(crawl=crawl, folder=hidden, title="Diary", url="https://example.org/private", config={"PERMISSIONS": "private"})
    smart = Folder.objects.create(name="Recent studies", rules={"query": 'folder:"Some folder name" AND title:Study', "limit": 1})
    for value in [child.name, "Papers / Some folder name", parent.name, smart.name, str(child.pk)]:
        plan = SnapshotSearch(Snapshot.objects.all(), f'folder:"{value}"')
        assert list(plan.sql_queryset().values_list("pk", flat=True)) == [row.pk]
    choices = client.get(reverse("search-suggestions"), {"operator": "folder"}, HTTP_HOST=WEB_TEST_HOST).json()["values"]
    assert "Papers / Some folder name" in choices and smart.name in choices and hidden.name not in choices
    with pytest.raises(ValidationError, match="cycle"):
        RuleQuery().compile({"query": 'folder:"Recent studies"'}, stack=(str(smart.pk),))


def test_hostname_page_probes_only_the_selected_rows(crawl):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from archivebox.misc.paginators import snapshot_page

    fragments = "solar sun energy grid battery power electric inverter photovoltaic storage charge panel".split()
    hosts = ["unmatched.example"] + [f"{part}.example" for part in fragments]
    rows = [Snapshot.objects.create(crawl=crawl, url=f"https://{hosts[index % len(hosts)]}/{index}") for index in range(28)]
    scope = Snapshot.objects.order_by("-created_at", "-pk").values_list("pk", flat=True)
    query = SnapshotSearch(scope, " OR ".join(f"domain:{part}" for part in fragments)).sql_queryset()
    expected = [row.pk for index, row in reversed(list(enumerate(rows))) if index % len(hosts)]
    assert list(query.all()) == expected
    with CaptureQueriesContext(connection) as queries:
        assert snapshot_page(query, base_queryset=scope, start=0, size=3) == expected[:3]
    assert snapshot_page(query, base_queryset=scope, start=3, size=3) == expected[3:6]
    assert query.count() == len(expected)
    if connection.vendor == "sqlite":
        assert queries
        assert all("SELECT DISTINCT" not in statement["sql"] for statement in queries)
