"""Query semantics at the ORM, CLI, HTTP and permission boundaries."""

import json
from datetime import UTC, datetime
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
    result = client.get(reverse("public-search-stream"), {**params, "search_url": path + "?" + urlencode(params)}, HTTP_HOST=WEB_TEST_HOST)
    assert consume_streaming_response(result).splitlines()[-1].strip() == b"1"
    page = client.get(path, params, HTTP_HOST=WEB_TEST_HOST)
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
