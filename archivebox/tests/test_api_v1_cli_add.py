import pytest
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from .conftest import (
    api_client_request,
    cli_env,
    create_admin_and_token,
    get_free_port,
    init_archive,
    live_api_request,
    start_archivebox_server,
    stop_server,
)
from archivebox.core.models import Snapshot, SnapshotTag
from archivebox.crawls.models import Crawl
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


IMPORT_FORMAT_EXPECTATIONS = {
    "rss": {
        "url": "https://example.com/",
        "title": "RSS Example Import",
        "date": "2024-01-01",
        "tags": {"rss-tag", "metadata"},
    },
    "netscape": {
        "url": "https://www.iana.org/domains/reserved",
        "title": "IANA Reserved Domains",
        "date": "2024-01-02",
        "tags": {"netscape-tag", "metadata"},
    },
    "dom": {
        "url": "https://www.iana.org/help/example-domains",
    },
    "json": {
        "url": "https://example.com/?archivebox-json-import=1",
        "title": "JSON Import Example",
        "date": "2024-01-03",
        "tags": {"json-tag", "metadata"},
    },
    "jsonl": {
        "url": "https://example.com/?archivebox-jsonl-import=1",
        "title": "JSONL Import Example",
        "date": "2024-01-04",
        "tags": {"jsonl-tag", "metadata"},
    },
    "txt": {
        "url": "https://example.org/",
    },
}


def write_import_format_files(base_dir: Path) -> dict[str, Path]:
    files = {
        "rss": base_dir / "test_rss.xml",
        "netscape": base_dir / "test_netscape.html",
        "dom": base_dir / "test_dom.html",
        "json": base_dir / "test_bookmarks.json",
        "jsonl": base_dir / "test_bookmarks.jsonl",
        "txt": base_dir / "test_urls.txt",
    }
    files["rss"].write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ArchiveBox RSS import fixture</title>
    <link>https://example.com/</link>
    <description>ArchiveBox RSS import fixture</description>
    <item>
      <title>RSS Example Import</title>
      <link>https://example.com/</link>
      <guid>https://example.com/</guid>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
      <category>rss-tag</category>
      <category>metadata</category>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )
    files["netscape"].write_text(
        """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
  <DT><A HREF="https://www.iana.org/domains/reserved" ADD_DATE="1704153600" TAGS="netscape-tag,metadata">IANA Reserved Domains</A>
</DL><p>
""",
        encoding="utf-8",
    )
    files["dom"].write_text(
        """<!doctype html>
<html>
  <head><title>DOM import fixture</title></head>
  <body>
    <a href="https://www.iana.org/help/example-domains">IANA Example Domains</a>
  </body>
</html>
""",
        encoding="utf-8",
    )
    files["json"].write_text(
        json.dumps(
            {
                "url": "https://example.com/?archivebox-json-import=1",
                "title": "JSON Import Example",
                "tags": ["json-tag", "metadata"],
                "bookmarked_at": "2024-01-03T00:00:00+00:00",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    files["jsonl"].write_text(
        json.dumps(
            {
                "url": "https://example.com/?archivebox-jsonl-import=1",
                "title": "JSONL Import Example",
                "tags": "jsonl-tag,metadata",
                "bookmarked_at": "2024-01-04T00:00:00+00:00",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    files["txt"].write_text(
        "Plain text import fixture containing https://example.org/ as a real live URL.\n",
        encoding="utf-8",
    )
    return files


IMPORT_FORMAT_ENV = {
    "USE_COLOR": "False",
    "SHOW_PROGRESS": "False",
    "PLUGINS": "parse_html_urls,parse_jsonl_urls,parse_netscape_urls,parse_rss_urls,parse_txt_urls",
    "USE_CHROME": "False",
    "URL_ALLOWLIST": r"example\.com|example\.org|iana\.org|www\.iana\.org",
}


def wait_for_expected_import_snapshots(
    cwd: Path,
    expected_urls: set[str],
    *,
    timeout: float = 180.0,
    expected_tags: set[str] | None = None,
) -> None:
    import time

    allowed_statuses = {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
    deadline = time.time() + timeout
    while time.time() < deadline:
        with use_archivebox_db(cwd):
            snapshots = list(Snapshot.objects.filter(url__in=expected_urls).values("id", "url", "status"))
            tag_names_by_snapshot_id = {}
            if expected_tags and snapshots:
                for snapshot_id, tag_name in SnapshotTag.objects.filter(
                    snapshot_id__in=[snapshot["id"] for snapshot in snapshots],
                ).values_list("snapshot_id", "tag__name"):
                    tag_names_by_snapshot_id.setdefault(snapshot_id, set()).add(tag_name)
        counts = {url: 0 for url in expected_urls}
        bad_statuses = []
        missing_tags = {}
        for snapshot in snapshots:
            counts[snapshot["url"]] += 1
            if snapshot["status"] not in allowed_statuses:
                bad_statuses.append((snapshot["url"], snapshot["status"]))
            if expected_tags:
                tag_names = tag_names_by_snapshot_id.get(snapshot["id"], set())
                missing = expected_tags - tag_names
                if missing:
                    missing_tags[snapshot["url"]] = missing
        if all(count == 1 for count in counts.values()) and not bad_statuses and not missing_tags:
            return
        time.sleep(1)
    raise AssertionError(
        f"timed out waiting for one queued/started/sealed snapshot per URL, got counts={counts}, bad_statuses={bad_statuses}, missing_tags={missing_tags}",
    )


def malicious_add_inputs(tmp_path: Path, *, safe_url: str) -> tuple[list[str], Path]:
    other_crawl_source = tmp_path / "sources" / "other_crawl_source.txt"
    other_crawl_source.parent.mkdir(parents=True, exist_ok=True)
    other_crawl_source.write_text("https://example.com/not-owned-by-this-crawl\n", encoding="utf-8")
    canary = tmp_path / "archivebox_shell_injection_canary"
    return (
        [
            safe_url,
            "file:///etc/hosts",
            "/etc/hosts",
            "../../../../etc/passwd",
            f"file://{other_crawl_source}",
            str(other_crawl_source),
            f"'; touch {canary}; #",
            f'" && touch {canary} && echo "',
            f"$(touch {canary})",
            f"`touch {canary}`",
            """<?xml version="1.0"?>
<!DOCTYPE rss [
  <!ENTITY localfile SYSTEM "file:///etc/hosts">
]>
<rss version="2.0" xmlns:xi="http://www.w3.org/2001/XInclude">
  <channel>
    <item><title>&localfile;</title><link>file:///etc/passwd</link></item>
    <xi:include href="file:///etc/hosts" parse="text"/>
  </channel>
</rss>""",
        ],
        canary,
    )


def assert_no_file_or_shell_payload_snapshots(cwd: Path, *, canary: Path) -> None:
    with use_archivebox_db(cwd):
        snapshots = list(Snapshot.objects.all())
    assert not canary.exists()
    assert not [snapshot.url for snapshot in snapshots if str(snapshot.url).startswith("file:")]
    for forbidden in ("/etc/hosts", "/etc/passwd", "other_crawl_source", "archivebox_shell_injection_canary"):
        assert not [snapshot.url for snapshot in snapshots if forbidden in str(snapshot.url)]


def test_basic_success_case_request(client, tmp_path, api_headers):
    init_archive(tmp_path)
    submitted_url = "https://example.com/api-cli-add-basic"

    response = api_client_request(
        client,
        "post",
        "/api/v1/cli/add",
        payload={
            "urls": [submitted_url],
            "depth": 0,
            "parser": "url_list",
            "plugins": "__archivebox_test_no_plugins__",
            "index_only": True,
        },
        headers=api_headers,
    )

    assert response.status_code == 200, response.content
    assert response.json()["success"] is True
    crawl = Crawl.objects.get()
    assert json.loads(crawl.urls) == {"type": "CrawlSeed", "url": submitted_url, "depth": 0}
    assert Snapshot.objects.count() == 0


@pytest.mark.timeout(180)
def test_api_cli_add_concurrent_first_time_default_persona_creation(tmp_path):
    """Concurrent live API add requests should share one first-created Default persona."""
    init_archive(tmp_path)
    with use_archivebox_db(tmp_path):
        from archivebox.personas.models import Persona

        Persona.objects.filter(name="Default").delete()
        assert Persona.objects.filter(name="Default").count() == 0

    port = get_free_port()
    env = cli_env(port=port, server=True, USE_COLOR="False", SHOW_PROGRESS="False")
    api_token = create_admin_and_token(tmp_path)
    submitted_urls = [f"https://example.com/api-cli-add-concurrent-persona-{idx}" for idx in range(4)]
    start = Event()

    def post_add(url: str):
        start.wait(timeout=10)
        return live_api_request(
            port,
            "post",
            "/api/v1/cli/add",
            api_token=api_token,
            timeout=60,
            json={
                "urls": [url],
                "depth": 0,
                "parser": "url_list",
                "plugins": "__archivebox_test_no_plugins__",
                "index_only": True,
            },
        )

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        with ThreadPoolExecutor(max_workers=len(submitted_urls)) as pool:
            futures = [pool.submit(post_add, url) for url in submitted_urls]
            start.set()
            responses = [future.result(timeout=75) for future in futures]
    finally:
        stop_server(tmp_path)

    assert [response.status_code for response in responses] == [200] * len(responses), [response.text[:500] for response in responses]
    bodies = [response.json() for response in responses]
    assert all(body["success"] is True for body in bodies)
    assert {body["result"]["queued_urls"][0] for body in bodies} == set(submitted_urls)

    with use_archivebox_db(tmp_path):
        from archivebox.personas.models import Persona

        assert Persona.objects.filter(name="Default").count() == 1
        crawls = list(Crawl.objects.order_by("urls").values_list("urls", flat=True))
        assert Snapshot.objects.count() == 0

    expected_crawl_sources = sorted(
        json.dumps({"type": "CrawlSeed", "url": url, "depth": 0}, separators=(",", ":")) for url in submitted_urls
    )
    assert crawls == expected_crawl_sources


@pytest.mark.timeout(360)
def test_api_cli_add_import_text_formats_preserve_metadata_and_crawl_inner_urls(tmp_path):
    """REST API add should accept rich import text and queue real inner URLs with metadata preserved."""
    init_archive(tmp_path)
    import_files = write_import_format_files(tmp_path)
    expected_urls = {case["url"] for case in IMPORT_FORMAT_EXPECTATIONS.values()}
    port = get_free_port()
    env = cli_env(port=port, server=True, **IMPORT_FORMAT_ENV)
    api_token = create_admin_and_token(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        for import_name, import_path in import_files.items():
            response = live_api_request(
                port,
                "post",
                "/api/v1/cli/add",
                api_token=api_token,
                json={
                    "urls": [import_path.read_text(encoding="utf-8")],
                    "depth": 0,
                    "tag": "api-import",
                    "plugins": IMPORT_FORMAT_ENV["PLUGINS"],
                    "index_only": False,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["success"] is True
            assert body["result"]["crawl_id"]
            with use_archivebox_db(tmp_path):
                crawl = Crawl.objects.get(id=body["result"]["crawl_id"])
            source_text = import_path.read_text(encoding="utf-8")
            assert crawl.urls == source_text

        deadline = time.time() + 240
        root_counts = {}
        while time.time() < deadline:
            with use_archivebox_db(tmp_path):
                root_counts = {
                    str(crawl.id): crawl.snapshot_set.filter(url=Snapshot.INTERNAL_INPUT_URL).count() for crawl in Crawl.objects.all()
                }
            if root_counts and all(count == 1 for count in root_counts.values()):
                break
            time.sleep(1)
        assert root_counts and all(count == 1 for count in root_counts.values()), root_counts
        with use_archivebox_db(tmp_path):
            for crawl in Crawl.objects.all():
                root_snapshot = crawl.snapshot_set.get(url=Snapshot.INTERNAL_INPUT_URL)
                root_input = (root_snapshot.output_dir / "staticfile" / "stdin.txt").read_text(encoding="utf-8")
                assert root_input == crawl.urls
        stop_server(tmp_path)
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_expected_import_snapshots(tmp_path, expected_urls)

        for import_name, expected in IMPORT_FORMAT_EXPECTATIONS.items():
            with use_archivebox_db(tmp_path):
                snapshot = Snapshot.objects.filter(url=expected["url"]).order_by("-created_at").first()
                assert snapshot is not None, f"{import_name} did not create Snapshot for {expected['url']}"
                snapshot_id = str(snapshot.id)

            snapshot_response = live_api_request(
                port,
                "get",
                f"/api/v1/core/snapshot/{snapshot_id}",
                api_token=api_token,
            )
            assert snapshot_response.status_code == 200, snapshot_response.text
            assert snapshot_response.json()["url"] == expected["url"]
    finally:
        stop_server(tmp_path)

    with use_archivebox_db(tmp_path):
        crawls = list(Crawl.objects.order_by("created_at"))
        snapshots_by_url = {snapshot.url: snapshot for snapshot in Snapshot.objects.prefetch_related("tags").filter(url__in=expected_urls)}
        tags_by_url = {snapshot.url: set(snapshot.tags.values_list("name", flat=True)) for snapshot in snapshots_by_url.values()}

    assert len(crawls) == len(import_files)
    assert [crawl.urls for crawl in crawls] == [path.read_text(encoding="utf-8") for path in import_files.values()]
    assert all(crawl.tags_str == "api-import" for crawl in crawls)
    assert all(crawl.status in {Crawl.StatusChoices.STARTED, Crawl.StatusChoices.SEALED} for crawl in crawls)
    assert len(snapshots_by_url) == len(expected_urls)

    for import_name, expected in IMPORT_FORMAT_EXPECTATIONS.items():
        snapshot = snapshots_by_url.get(expected["url"])
        assert snapshot is not None, f"{import_name} did not create Snapshot for {expected['url']}"
        assert snapshot.status in {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
        if expected.get("title"):
            assert snapshot.title == expected["title"]
        if expected.get("date"):
            assert snapshot.bookmarked_at.date().isoformat() == expected["date"]
        if expected.get("tags"):
            assert expected["tags"] | {"api-import"} <= tags_by_url[snapshot.url]


@pytest.mark.timeout(240)
def test_api_cli_add_rejects_file_path_and_shell_injection_payloads(tmp_path):
    """REST add must not let path, file://, traversal, or shell strings become archiveable URLs."""
    init_archive(tmp_path)
    safe_url = "https://example.com/?archivebox-api-security=1"
    inputs, canary = malicious_add_inputs(tmp_path, safe_url=safe_url)
    port = get_free_port()
    env = cli_env(port=port, server=True, **IMPORT_FORMAT_ENV)
    api_token = create_admin_and_token(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        response = live_api_request(
            port,
            "post",
            "/api/v1/cli/add",
            api_token=api_token,
            json={
                "urls": inputs,
                "depth": 0,
                "tag": "api-security",
                "plugins": IMPORT_FORMAT_ENV["PLUGINS"],
                "index_only": False,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True

        wait_for_expected_import_snapshots(tmp_path, {safe_url}, timeout=120)
    finally:
        stop_server(tmp_path)

    wait_for_expected_import_snapshots(tmp_path, {safe_url}, timeout=30, expected_tags={"api-security"})
    assert_no_file_or_shell_payload_snapshots(tmp_path, canary=canary)
    with use_archivebox_db(tmp_path):
        snapshot = Snapshot.objects.get(url=safe_url)
        crawl = Crawl.objects.get()
    assert crawl.status in {Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED, Crawl.StatusChoices.SEALED}
    assert snapshot.status in {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
    with use_archivebox_db(tmp_path):
        tag_names = set(SnapshotTag.objects.filter(snapshot=snapshot).values_list("tag__name", flat=True))
    assert "api-security" in tag_names
