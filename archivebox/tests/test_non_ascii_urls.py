"""Non-ASCII (IRI) and credentialed URLs through every ArchiveBox intake path.

Snapshot URLs are stored and displayed as submitted (https://münchen.de/über
stays Unicode, https://user:pw@host:8443/ keeps its credentials and port). The
same resource also reaches ArchiveBox in its encoded URI form: browsers send
/web/https://example.com/%C3%BCber, Chrome reports outlinks as /%C3%BCber, and
users paste either. Those forms must find and dedupe against each other, and
hooks must receive a URL they can actually fetch.
"""

import base64
import json
import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.misc.util import iri_to_uri, validate_url
from archivebox.tests.conftest import api_client_request, cli_env, run_archivebox_cmd, run_queued_crawls
from archivebox.tests.test_orm_helpers import use_archivebox_db
from archivebox.tests.test_search import populate_admin_search_cache

ADMIN_HOST = "admin.archivebox.localhost:5797"


@pytest.fixture
def default_persona(db):
    # Match init/server startup; the add form requires the Default persona.
    return Persona.get_or_create_default()


IRI = "https://usér:pä ss@münchen.example:8443/über?q=ü"
URI = "https://us%C3%A9r:p%C3%A4%20ss@xn--mnchen-3ya.example:8443/%C3%BCber?q=%C3%BC"


def test_validate_url_keeps_iri_and_credentials_as_submitted():
    assert validate_url(IRI) == IRI
    assert validate_url(URI) == URI
    assert iri_to_uri(IRI) == URI
    assert iri_to_uri(URI) == URI
    # Already-ASCII URLs, including existing escapes, are never rewritten.
    ascii_url = "https://user:p%40ss@example.com:8443/a%20b?x=%C3%BC#frag"
    assert iri_to_uri(ascii_url) == ascii_url


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "http://ａｄｍｉｎ.archivebox.localhost:5797/admin/",
        "http://admin.archivebox.localhost．:5797/admin/",
        "http://１２７.０.０.１:5797/",
    ],
)
def test_self_archive_protection_folds_unicode_hostnames(url):
    # Chrome and wget both resolve these to ArchiveBox's own host (UTS #46
    # folds fullwidth letters, digits and dots), so they must be blocked too.
    assert Snapshot.is_archivebox_internal_url(url)


@pytest.mark.django_db
@pytest.mark.parametrize("pattern", ["münchen.example", "xn--mnchen-3ya.example"])
def test_url_filters_match_idn_domains_in_either_form(admin_user, pattern):
    crawl = Crawl.objects.create(
        urls="\n".join(
            [
                "https://münchen.example/unicode",
                "https://xn--mnchen-3ya.example/punycode",
                "https://other.example/",
            ],
        ),
        created_by=admin_user,
        config={"URL_ALLOWLIST": pattern},
    )

    created = crawl.create_snapshots_from_urls()

    assert [snapshot.url for snapshot in created] == [
        "https://münchen.example/unicode",
        "https://xn--mnchen-3ya.example/punycode",
    ]


@pytest.mark.django_db
def test_crawl_dedupes_percent_encoded_equivalents(admin_user):
    crawl = Crawl.objects.create(urls=f"{IRI}\n{URI}", max_depth=1, created_by=admin_user)

    created = crawl.create_snapshots_from_urls()

    # The first submitted form is stored; its encoded twin is the same URL.
    assert [snapshot.url for snapshot in created] == [IRI]

    # Chrome outlinks arrive encoded while HTML hrefs stay Unicode.
    children = crawl.create_discovered_snapshots(
        created[0],
        [
            {"url": "https://example.com/kinder/ü"},
            {"url": "https://example.com/kinder/%C3%BC"},
            {"url": URI},
        ],
        depth=1,
    )
    assert [snapshot.url for snapshot in children] == ["https://example.com/kinder/ü"]

    # ONLY_NEW (the default) skips URLs already archived in any form.
    later = Crawl.objects.create(urls="https://example.com/kinder/%C3%BC", created_by=admin_user)
    assert later.create_snapshots_from_urls() == []


@pytest.mark.django_db
def test_add_form_stores_iri_and_credentials_as_submitted(admin_client, default_persona):
    response = admin_client.post(
        reverse("add"),
        data={
            "url": IRI,
            "tag": "",
            "depth": "0",
            "max_urls": "0",
            "crawl_max_size": "0",
            "snapshot_max_size": "0",
            "url_filters_allowlist": "",
            "url_filters_denylist": "",
            "notes": "",
            "schedule": "",
            "persona": "Default",
            "permissions": "public",
            "config": "{}",
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 302, response.context["form"].errors
    crawl = Crawl.objects.get()
    assert crawl.urls == IRI
    assert [snapshot.url for snapshot in crawl.create_snapshots_from_urls()] == [IRI]


@pytest.mark.django_db
def test_api_add_and_crawl_store_iri_and_credentials_as_submitted(client, api_headers):
    response = api_client_request(
        client,
        "post",
        "/api/v1/cli/add",
        payload={"urls": [IRI], "plugins": "__archivebox_test_no_plugins__", "index_only": True},
        headers=api_headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["result"]["queued_urls"] == [IRI]

    response = api_client_request(
        client,
        "post",
        "/api/v1/crawls/crawls",
        payload={"urls": [URI], "max_depth": 0},
        headers=api_headers,
    )
    assert response.status_code == 200, response.content
    assert [crawl.urls for crawl in Crawl.objects.order_by("created_at")] == [IRI, URI]

    # The browser-extension snapshot endpoint dedupes the encoded twin (ONLY_NEW).
    created = api_client_request(client, "post", "/api/v1/core/snapshots", payload={"url": IRI}, headers=api_headers)
    assert created.status_code == 200, created.content
    twin = api_client_request(client, "post", "/api/v1/core/snapshots", payload={"url": URI}, headers=api_headers)
    assert twin.status_code == 200, twin.content
    assert twin.json()["id"] == created.json()["id"]
    assert list(Snapshot.objects.values_list("url", flat=True)) == [IRI]


@pytest.mark.django_db
def test_web_add_route_keeps_query_string_and_literal_escapes(admin_client, default_persona):
    # Browsers send the target percent-encoded; Django decodes the path once.
    response = admin_client.get("/web/https://example.com/neu?x=%C3%BC&y=a%26b", HTTP_HOST=ADMIN_HOST)
    assert response.status_code == 302, response.content.decode()
    snapshot = Snapshot.objects.get()
    assert snapshot.url == "https://example.com/neu?x=ü&y=a%26b"

    # Requesting the same target again reuses that snapshot.
    again = admin_client.get("/web/https://example.com/neu?x=%C3%BC&y=a%26b", HTTP_HOST=ADMIN_HOST)
    assert again.status_code == 302
    assert again["Location"] == response["Location"]
    assert Snapshot.objects.count() == 1

    # %2520 is a literal "%20" in the target URL, not a second encoding layer.
    admin_client.get("/web/https://example.com/pfad/a%2520b", HTTP_HOST=ADMIN_HOST)
    assert Snapshot.objects.filter(url="https://example.com/pfad/a%20b").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stored", "requested"),
    [
        # Stored as the encoded URI, requested by a browser (decoded by Django).
        ("https://example.com/%C3%BCber?q=%C3%BC", "/web/https://example.com/%C3%BCber?q=%C3%BC"),
        # Stored as an IRI with a Unicode host, requested via its IDNA name.
        ("https://münchen.example/straße", "/web/https://xn--mnchen-3ya.example/stra%C3%9Fe"),
    ],
)
def test_web_route_finds_snapshot_stored_in_other_form(admin_client, admin_user, default_persona, stored, requested):
    crawl = Crawl.objects.create(urls=stored, created_by=admin_user)
    [snapshot] = crawl.create_snapshots_from_urls()
    # A same-host sibling makes a loose host-prefix fallback ambiguous.
    Crawl.objects.create(urls=re.sub(r"(//[^/]+/).*", r"\1andere", stored), created_by=admin_user).create_snapshots_from_urls()

    response = admin_client.get(requested, HTTP_HOST=ADMIN_HOST)

    assert response.status_code == 302, response.content.decode()
    assert str(snapshot.id) in response["Location"]
    assert Snapshot.objects.count() == 2


@pytest.mark.django_db
def test_memento_timegate_finds_capture_by_encoded_uri(admin_client, admin_user):
    crawl = Crawl.objects.create(urls="https://example.com/über?q=ü", created_by=admin_user)
    [snapshot] = crawl.create_snapshots_from_urls()
    Snapshot.objects.filter(pk=snapshot.pk).update(downloaded_at=timezone.now() - timedelta(minutes=1), output_size=1)

    response = admin_client.get("/archive/https://example.com/%C3%BCber?q=%C3%BC", HTTP_HOST=ADMIN_HOST)

    assert response.status_code == 302, response.content.decode()
    assert str(snapshot.id) in response["Location"]
    # Link headers must be ASCII: the original URI uses the IDNA/UTF-8 form.
    assert '<https://example.com/%C3%BCber?q=%C3%BC>; rel="original"' in response["Link"]


# The search stream reads from another thread, so rows must be committed.
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("query", ["https://example.com/über", "https://example.com/%C3%BCber"])
def test_admin_search_finds_iri_snapshot_by_either_form(admin_client, admin_user, query):
    crawl = Crawl.objects.create(urls="https://example.com/über?q=ü", created_by=admin_user)
    [snapshot] = crawl.create_snapshots_from_urls()

    path = reverse("admin:core_snapshot_changelist")
    params = {"q": query, "search_mode": "meta"}
    response = populate_admin_search_cache(admin_client, path, params)

    assert response.status_code == 200
    assert list(response.context["cl"].queryset.values_list("pk", flat=True)) == [snapshot.pk]


@pytest.mark.timeout(240)
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("via", ["args", "stdin"])
def test_cli_add_fetches_iri_with_credentials_and_dedupes_encoded_twin(initialized_archive, httpserver, via):
    user, password = "usér", "pä%20ss%40"
    decoded = "usér:pä ss@"
    url = f"http://{user}:{password}@127.0.0.1:{httpserver.port}/über/seite?q=ü"
    auth = "Basic " + base64.b64encode(decoded.encode()).decode()
    httpserver.expect_request("/über/seite", headers={"Authorization": auth}).respond_with_data(
        "<html><head><title>Grüße</title></head><body>Grüße</body></html>",
        content_type="text/html; charset=utf-8",
    )
    httpserver.expect_request("/über/seite").respond_with_data("", status=401, headers={"WWW-Authenticate": 'Basic realm="t"'})
    env = cli_env(wget=True, WGET_WARC_ENABLED="False", URL_ALLOWLIST="", USE_CHROME="False")

    result = run_archivebox_cmd(
        ["add", "--plugins=wget", *([url] if via == "args" else [])],
        input=f"{url}\n" if via == "stdin" else None,
        cwd=initialized_archive,
        env=env,
        timeout=200,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get()
        hook_cmds = [process.cmd for result in snapshot.archiveresult_set.all() if (process := result.process)]
        output_dir = snapshot.output_dir
    assert snapshot.url == url
    assert hook_cmds and all(f"--url={url}" in cmd for cmd in hook_cmds), hook_cmds
    fetched = [(req.environ["REQUEST_URI"], req.headers.get("Authorization")) for req, _ in httpserver.log]
    assert ("/%C3%BCber/seite?q=%C3%BC", auth) in fetched, fetched
    saved = list((output_dir / "wget").rglob("seite*.html"))
    assert saved and "Grüße" in saved[0].read_text(encoding="utf-8"), saved

    # Adding the percent-encoded twin is a repeat of an archived URL (ONLY_NEW).
    twin = iri_to_uri(url)
    assert twin != url
    result = run_archivebox_cmd(["add", "--index-only", twin], cwd=initialized_archive, env=cli_env(disable_extractors=True))
    assert result.returncode == 0, result.stdout + result.stderr
    run_queued_crawls(initialized_archive, cli_env(disable_extractors=True))
    with use_archivebox_db(initialized_archive):
        assert list(Snapshot.objects.values_list("url", flat=True)) == [url]
        assert Crawl.objects.order_by("-created_at").first().urls == twin

    # Re-running extractors by the encoded URL targets the stored IRI snapshot.
    result = run_archivebox_cmd(["extract", "--plugins=wget", twin], cwd=initialized_archive, env=env, timeout=200)
    assert result.returncode == 0, result.stdout + result.stderr
    extracted = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert {record["snapshot_id"] for record in extracted if record.get("type") == "ArchiveResult"} == {str(snapshot.id)}, extracted
