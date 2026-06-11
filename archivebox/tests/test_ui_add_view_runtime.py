import re
import time
import json
from pathlib import Path

import pytest
import requests

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.tests.test_orm_helpers import use_archivebox_db
from .conftest import (
    cli_env,
    create_admin_and_token,
    get_depth_counts,
    get_free_port,
    init_archive,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_server,
    wait_for_http,
)

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


def wait_for_import_processing(cwd: Path, expected_urls: set[str], *, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with use_archivebox_db(cwd):
            snapshot_started = Snapshot.objects.filter(url__in=expected_urls).exists()
        if snapshot_started:
            return
        time.sleep(1)
    raise AssertionError("timed out waiting for import crawl processing to start")


def wait_for_expected_import_snapshots(cwd: Path, expected_urls: set[str], *, timeout: float = 180.0) -> None:
    allowed_statuses = {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
    deadline = time.time() + timeout
    while time.time() < deadline:
        with use_archivebox_db(cwd):
            rows = list(Snapshot.objects.filter(url__in=expected_urls).values_list("url", "status"))
        counts = {url: 0 for url in expected_urls}
        bad_statuses = []
        for url, status in rows:
            counts[url] += 1
            if status not in allowed_statuses:
                bad_statuses.append((url, status))
        if all(count == 1 for count in counts.values()) and not bad_statuses:
            return
        time.sleep(1)
    raise AssertionError(
        f"timed out waiting for one queued/started/sealed snapshot per URL, got counts={counts}, bad_statuses={bad_statuses}",
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


@pytest.mark.timeout(180)
def test_add_view_restarts_stopped_supervisord_runner(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(
        port=port,
        PLUGINS="wget",
        PUBLIC_ADD_VIEW="True",
        PYTEST_CURRENT_TEST="",
    )
    create_admin_and_token(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        _wait_for_worker_state(tmp_path, "worker_runner", "RUNNING")
        _stop_worker(tmp_path, "worker_runner")
        assert _worker_state(tmp_path, "worker_runner") != "RUNNING"

        session, csrf_token = _login_to_add_view(port)
        response = session.post(
            f"http://127.0.0.1:{port}/add/",
            headers={"Host": f"admin.archivebox.localhost:{port}", "Referer": f"http://admin.archivebox.localhost:{port}/add/"},
            data={
                "url": recursive_test_site["root_url"],
                "depth": "0",
                "max_urls": "1",
                "crawl_max_size": "0",
                "snapshot_max_size": "0",
                "main_plugins": ["wget"],
                "tag": "restart-supervised-runner",
                "url_filters_allowlist": r"127\.0\.0\.1[:/].*",
                "url_filters_denylist": "",
                "schedule": "",
                "notes": "restart stopped supervised runner",
                "persona": "Default",
                "permissions": "public",
                "start_paused": "",
                "config": "{}",
                "csrfmiddlewaretoken": csrf_token,
            },
            timeout=10,
            allow_redirects=False,
        )
        assert response.status_code in (302, 303), response.text

        _wait_for_worker_state(tmp_path, "worker_runner", "RUNNING")
        with use_archivebox_db(tmp_path):
            crawl = Crawl.objects.order_by("-created_at").first()
            assert crawl is not None
            assert crawl.tags_str == "restart-supervised-runner"
            assert json.loads(crawl.urls) == {
                "type": "CrawlSeed",
                "url": recursive_test_site["root_url"],
                "depth": 0,
            }
    finally:
        stop_server(tmp_path)


def _login_to_add_view(port: int) -> tuple[requests.Session, str]:
    session = requests.Session()
    wait_for_http(port, host=f"admin.archivebox.localhost:{port}", path="/admin/login/")
    login_page = session.get(
        f"http://127.0.0.1:{port}/admin/login/",
        headers={"Host": f"admin.archivebox.localhost:{port}"},
        timeout=10,
    )
    assert login_page.status_code == 200
    csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login_page.text)
    assert csrf_match, login_page.text[:500]
    login_response = session.post(
        f"http://127.0.0.1:{port}/admin/login/",
        headers={"Host": f"admin.archivebox.localhost:{port}", "Referer": f"http://admin.archivebox.localhost:{port}/admin/login/"},
        data={
            "username": "apitestadmin",
            "password": "testpass123",
            "csrfmiddlewaretoken": csrf_match.group(1),
            "next": "/add/",
        },
        timeout=10,
        allow_redirects=False,
    )
    assert login_response.status_code in (302, 303), login_response.text
    add_page = wait_for_http(port, host=f"admin.archivebox.localhost:{port}", path="/add/")
    assert add_page.status_code == 200
    add_csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', add_page.text)
    assert add_csrf_match, add_page.text[:500]
    return session, add_csrf_match.group(1)


def _worker_state(cwd, worker_name: str) -> str | None:
    script = f"""
import json
from archivebox.workers.supervisord_util import get_existing_supervisord_process, get_worker
supervisor = get_existing_supervisord_process()
worker = get_worker(supervisor, {worker_name!r}) if supervisor else None
print(json.dumps(worker))
"""
    _cmd_result = run_archivebox_cmd(["manage", "shell", "-c", script], cwd=cwd, timeout=60)
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout
    import json

    worker = json.loads(stdout.strip().splitlines()[-1])
    return worker.get("statename") if worker else None


def _stop_worker(cwd, worker_name: str) -> None:
    script = f"""
from archivebox.workers.supervisord_util import get_existing_supervisord_process, stop_worker
supervisor = get_existing_supervisord_process()
assert supervisor is not None
stop_worker(supervisor, {worker_name!r})
print("stopped")
"""
    _cmd_result = run_archivebox_cmd(["manage", "shell", "-c", script], cwd=cwd, timeout=60)
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout


def _wait_for_worker_state(cwd, worker_name: str, statename: str, timeout: int = 45) -> None:
    deadline = time.time() + timeout
    state = None
    while time.time() < deadline:
        state = _worker_state(cwd, worker_name)
        if state == statename:
            return
        time.sleep(1)
    raise AssertionError(f"Timed out waiting for {worker_name}={statename}, last state={state}")


@pytest.mark.timeout(240)
def test_public_add_view_depth_one_crawl_skips_unreadable_persona_profile_entries(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    chrome_profile = tmp_path / "personas" / "Default" / "chrome_profile"
    default_profile = chrome_profile / "Default"
    default_profile.mkdir(parents=True, exist_ok=True)
    (default_profile / "Preferences").write_text('{"profile":{"name":"Default"}}', encoding="utf-8")
    unreadable_dir = chrome_profile / "ActorSafetyLists"
    unreadable_dir.mkdir(parents=True, exist_ok=True)
    (unreadable_dir / "Preferences").write_text("{}", encoding="utf-8")
    unreadable_dir.chmod(0)

    port = get_free_port()
    env = cli_env(
        port=port,
        PLUGINS="wget,parse_html_urls",
        SAVE_WGET="True",
        PUBLIC_INDEX="True",
        PUBLIC_ADD_VIEW="True",
        URL_ALLOWLIST=r"127\.0\.0\.1[:/].*",
    )

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        add_page = wait_for_http(port, host=f"web.archivebox.localhost:{port}", path="/add/")
        assert add_page.status_code == 200
        assert 'name="depth"' in add_page.text

        response = requests.post(
            f"http://127.0.0.1:{port}/add/",
            headers={"Host": f"web.archivebox.localhost:{port}", "Referer": f"http://web.archivebox.localhost:{port}/add/"},
            data={
                "url": recursive_test_site["root_url"],
                "depth": "1",
                "max_urls": "10",
                "crawl_max_size": "0",
                "snapshot_max_size": "0",
                "tag": "public-depth-one-unreadable-profile",
                "url_filters_allowlist": r"127\.0\.0\.1[:/].*",
                "url_filters_denylist": "",
                "schedule": "",
                "notes": "public depth one with unreadable chrome profile entries",
                "persona": "Default",
                "permissions": "public",
                "start_paused": "",
                "config": "{}",
            },
            timeout=10,
            allow_redirects=False,
        )
        assert response.status_code in (302, 303), response.text

        deadline = time.time() + 180
        while time.time() < deadline:
            with use_archivebox_db(tmp_path):
                crawl = Crawl.objects.order_by("-created_at").first()
                depth_counts = get_depth_counts(tmp_path)
                child_urls = set(Snapshot.objects.filter(depth=1).values_list("url", flat=True))
                failed_results = list(
                    ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.FAILED).values_list("plugin", "output_str"),
                )
            if depth_counts.get(0, 0) >= 1 and set(recursive_test_site["child_urls"]).issubset(child_urls):
                break
            assert not failed_results
            time.sleep(2)
        else:
            raise AssertionError(f"timed out waiting for depth=1 crawl, got depth counts {get_depth_counts(tmp_path)}")

        with use_archivebox_db(tmp_path):
            crawl = Crawl.objects.order_by("-created_at").first()
            snapshot_rows = list(Snapshot.objects.order_by("depth", "url").values_list("url", "depth", "status"))
            result_rows = list(ArchiveResult.objects.order_by("plugin", "status").values_list("plugin", "status", "output_size"))
    finally:
        unreadable_dir.chmod(0o700)
        stop_server(tmp_path)

    assert crawl is not None
    assert crawl.max_depth == 1
    assert crawl.status in {Crawl.StatusChoices.STARTED, Crawl.StatusChoices.SEALED}
    assert (recursive_test_site["root_url"], 0, Snapshot.StatusChoices.SEALED) in snapshot_rows
    assert set(recursive_test_site["child_urls"]).issubset({url for url, depth, _status in snapshot_rows if depth == 1})
    assert all(
        status in {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
        for _url, _depth, status in snapshot_rows
    )
    assert not [row for row in result_rows if row[1] == ArchiveResult.StatusChoices.FAILED]
    assert any(plugin == "wget" and status == ArchiveResult.StatusChoices.SUCCEEDED and size > 0 for plugin, status, size in result_rows)
    assert any(plugin == "parse_html_urls" and status == ArchiveResult.StatusChoices.SUCCEEDED for plugin, status, _size in result_rows)


@pytest.mark.timeout(420)
def test_public_add_view_import_text_formats_preserve_metadata_and_resume_without_duplicates(tmp_path):
    """Public /add/ textarea should import rich text, survive runner restart, and preserve one row per URL."""
    init_archive(tmp_path)
    import_files = write_import_format_files(tmp_path)
    expected_urls = {case["url"] for case in IMPORT_FORMAT_EXPECTATIONS.values()}

    port = get_free_port()
    env = cli_env(
        port=port,
        PLUGINS="parse_html_urls,parse_jsonl_urls,parse_netscape_urls,parse_rss_urls,parse_txt_urls,wget,headers",
        SAVE_WGET="True",
        SAVE_HEADERS="True",
        USE_CHROME="False",
        PUBLIC_INDEX="True",
        PUBLIC_ADD_VIEW="True",
        URL_ALLOWLIST=r"example\.com|example\.org|iana\.org|www\.iana\.org",
    )
    create_admin_and_token(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        add_page = wait_for_http(port, host=f"web.archivebox.localhost:{port}", path="/add/")
        assert add_page.status_code == 200
        assert 'name="url"' in add_page.text

        for import_path in import_files.values():
            source_text = import_path.read_text(encoding="utf-8")
            submitted_text = source_text.rstrip("\n")
            response = requests.post(
                f"http://127.0.0.1:{port}/add/",
                headers={"Host": f"web.archivebox.localhost:{port}", "Referer": f"http://web.archivebox.localhost:{port}/add/"},
                data={
                    "url": source_text,
                    "depth": "0",
                    "max_urls": "0",
                    "crawl_max_size": "0",
                    "snapshot_max_size": "0",
                    "tag": "public-ui-import",
                    "url_filters_allowlist": r"example\.com|example\.org|iana\.org|www\.iana\.org",
                    "url_filters_denylist": "",
                    "schedule": "",
                    "notes": "public add import formats",
                    "persona": "Default",
                    "permissions": "public",
                    "start_paused": "",
                    "config": "{}",
                },
                timeout=10,
                allow_redirects=False,
            )
            assert response.status_code in (302, 303), response.text
            deadline = time.time() + 60
            root_input = None
            while time.time() < deadline:
                with use_archivebox_db(tmp_path):
                    crawl = Crawl.objects.order_by("-created_at").first()
                    assert crawl is not None
                    assert crawl.urls == submitted_text
                    root_snapshot = crawl.snapshot_set.filter(url=Snapshot.INTERNAL_INPUT_URL).first()
                    if root_snapshot:
                        root_input = (root_snapshot.output_dir / "staticfile" / "stdin.txt").read_text(encoding="utf-8")
                        break
                time.sleep(1)
            assert root_input == submitted_text

        wait_for_import_processing(tmp_path, expected_urls)
        stop_server(tmp_path)
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_expected_import_snapshots(tmp_path, expected_urls)

        public_index = requests.get(
            f"http://127.0.0.1:{port}/",
            headers={"Host": f"web.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert public_index.status_code == 200
        for expected_url in expected_urls:
            assert expected_url in public_index.text
    finally:
        stop_server(tmp_path)

    with use_archivebox_db(tmp_path):
        crawls = list(Crawl.objects.order_by("created_at"))
        snapshots_by_url = {snapshot.url: snapshot for snapshot in Snapshot.objects.prefetch_related("tags").filter(url__in=expected_urls)}
        tags_by_url = {snapshot.url: set(snapshot.tags.values_list("name", flat=True)) for snapshot in snapshots_by_url.values()}

    assert len(crawls) == len(import_files)
    assert [crawl.urls for crawl in crawls] == [path.read_text(encoding="utf-8") for path in import_files.values()]
    assert all(crawl.tags_str == "public-ui-import" for crawl in crawls)
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
            assert expected["tags"] | {"public-ui-import"} <= tags_by_url[snapshot.url]


@pytest.mark.timeout(240)
def test_public_add_view_rejects_file_path_and_shell_injection_payloads(tmp_path):
    """Public /add/ must not archive local paths or execute shell-like textarea content."""
    init_archive(tmp_path)
    safe_url = "https://example.com/?archivebox-public-ui-security=1"
    inputs, canary = malicious_add_inputs(tmp_path, safe_url=safe_url)

    port = get_free_port()
    env = cli_env(
        port=port,
        PLUGINS="parse_html_urls,parse_jsonl_urls,parse_netscape_urls,parse_rss_urls,parse_txt_urls,wget,headers",
        SAVE_WGET="True",
        SAVE_HEADERS="True",
        USE_CHROME="False",
        PUBLIC_INDEX="True",
        PUBLIC_ADD_VIEW="True",
        URL_ALLOWLIST=r"example\.com|example\.org|iana\.org|www\.iana\.org",
    )
    create_admin_and_token(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        add_page = wait_for_http(port, host=f"web.archivebox.localhost:{port}", path="/add/")
        assert add_page.status_code == 200

        response = requests.post(
            f"http://127.0.0.1:{port}/add/",
            headers={"Host": f"web.archivebox.localhost:{port}", "Referer": f"http://web.archivebox.localhost:{port}/add/"},
            data={
                "url": "\n".join(inputs),
                "depth": "0",
                "max_urls": "0",
                "crawl_max_size": "0",
                "snapshot_max_size": "0",
                "tag": "public-ui-security",
                "url_filters_allowlist": r"example\.com|example\.org|iana\.org|www\.iana\.org",
                "url_filters_denylist": "",
                "schedule": "",
                "notes": "public add security payloads",
                "persona": "Default",
                "permissions": "public",
                "start_paused": "",
                "config": "{}",
            },
            timeout=10,
            allow_redirects=False,
        )
        assert response.status_code in (302, 303), response.text

        wait_for_import_processing(tmp_path, {safe_url})
        stop_server(tmp_path)
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_expected_import_snapshots(tmp_path, {safe_url}, timeout=120)

        public_index = requests.get(
            f"http://127.0.0.1:{port}/",
            headers={"Host": f"web.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert public_index.status_code == 200
        assert safe_url in public_index.text
    finally:
        stop_server(tmp_path)

    assert_no_file_or_shell_payload_snapshots(tmp_path, canary=canary)
    with use_archivebox_db(tmp_path):
        snapshot = Snapshot.objects.get(url=safe_url)
        crawl = Crawl.objects.get()
        tag_names = set(snapshot.tags.values_list("name", flat=True))
    assert crawl.status in {Crawl.StatusChoices.STARTED, Crawl.StatusChoices.SEALED}
    assert snapshot.status in {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
    assert "public-ui-security" in tag_names


@pytest.mark.timeout(180)
def test_add_view_post_creates_schedule_over_server(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True, PUBLIC_ADD_VIEW="True")
    create_admin_and_token(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        session = requests.Session()
        wait_for_http(port, host=f"admin.archivebox.localhost:{port}", path="/admin/login/")
        login_page = session.get(
            f"http://admin.archivebox.localhost:{port}/admin/login/",
            timeout=10,
        )
        assert login_page.status_code == 200
        csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login_page.text)
        assert csrf_match, login_page.text[:500]
        login_response = session.post(
            f"http://admin.archivebox.localhost:{port}/admin/login/",
            headers={"Referer": f"http://admin.archivebox.localhost:{port}/admin/login/"},
            data={
                "username": "apitestadmin",
                "password": "testpass123",
                "csrfmiddlewaretoken": csrf_match.group(1),
                "next": "/add/",
            },
            timeout=10,
            allow_redirects=False,
        )
        assert login_response.status_code in (302, 303), login_response.text
        wait_for_http(port, host=f"admin.archivebox.localhost:{port}", path="/add/")

        response = session.post(
            f"http://admin.archivebox.localhost:{port}/add/",
            headers={"Referer": f"http://admin.archivebox.localhost:{port}/add/"},
            data={
                "url": recursive_test_site["root_url"],
                "depth": "0",
                "max_urls": "0",
                "crawl_max_size": "0",
                "snapshot_max_size": "0",
                "schedule": "daily",
                "tag": "web-ui",
                "notes": "created from web ui",
                "persona": "Default",
                "permissions": "public",
                "config": "{}",
                "csrfmiddlewaretoken": csrf_match.group(1),
            },
            timeout=10,
            allow_redirects=False,
        )

        assert response.status_code in (302, 303), response.text

        with use_archivebox_db(tmp_path):
            schedule = CrawlSchedule.objects.select_related("template").order_by("-created_at").first()
            row = None
            if schedule:
                template_url = json.loads(schedule.template.urls)["url"]
                row = (schedule.schedule, template_url, schedule.template.tags_str)

        assert row == ("daily", recursive_test_site["root_url"], "web-ui")
    finally:
        stop_server(tmp_path)


@pytest.mark.timeout(240)
def test_add_view_depth_two_crawl_renders_outputs_over_server(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(
        port=port,
        PLUGINS="wget,parse_html_urls",
        PUBLIC_INDEX="True",
        PUBLIC_ADD_VIEW="True",
    )
    create_admin_and_token(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        session = requests.Session()
        wait_for_http(port, host=f"admin.archivebox.localhost:{port}", path="/admin/login/")
        login_page = session.get(
            f"http://127.0.0.1:{port}/admin/login/",
            headers={"Host": f"admin.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert login_page.status_code == 200
        csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login_page.text)
        assert csrf_match, login_page.text[:500]
        login_response = session.post(
            f"http://127.0.0.1:{port}/admin/login/",
            headers={"Host": f"admin.archivebox.localhost:{port}", "Referer": f"http://admin.archivebox.localhost:{port}/admin/login/"},
            data={
                "username": "apitestadmin",
                "password": "testpass123",
                "csrfmiddlewaretoken": csrf_match.group(1),
                "next": "/add/",
            },
            timeout=10,
            allow_redirects=False,
        )
        assert login_response.status_code in (302, 303), login_response.text
        add_page = wait_for_http(port, host=f"admin.archivebox.localhost:{port}", path="/add/")
        assert add_page.status_code == 200
        assert 'name="depth"' in add_page.text
        assert 'name="url"' in add_page.text

        response = session.post(
            f"http://127.0.0.1:{port}/add/",
            headers={"Host": f"admin.archivebox.localhost:{port}", "Referer": f"http://admin.archivebox.localhost:{port}/add/"},
            data={
                "url": recursive_test_site["root_url"],
                "depth": "2",
                "max_urls": "20",
                "crawl_max_size": "0",
                "snapshot_max_size": "0",
                "main_plugins": ["wget"],
                "postprocessing_plugins": ["parse_html_urls"],
                "tag": "web-depth-two",
                "url_filters_allowlist": r"127\.0\.0\.1[:/].*",
                "url_filters_denylist": "",
                "schedule": "",
                "notes": "created from running-server web ui",
                "persona": "Default",
                "permissions": "public",
                "start_paused": "",
                "config": "{}",
                "csrfmiddlewaretoken": csrf_match.group(1),
            },
            timeout=10,
            allow_redirects=False,
        )
        assert response.status_code in (302, 303), response.text

        deadline = time.time() + 180
        while time.time() < deadline:
            depth_counts = get_depth_counts(tmp_path)
            if (
                depth_counts.get(0, 0) >= 1
                and depth_counts.get(1, 0) >= len(recursive_test_site["child_urls"])
                and depth_counts.get(2, 0) >= len(recursive_test_site["deep_urls"])
            ):
                break
            time.sleep(2)
        else:
            raise AssertionError(f"timed out waiting for depth=2 crawl, got depth counts {get_depth_counts(tmp_path)}")

        with use_archivebox_db(tmp_path):
            depth_counts = get_depth_counts(tmp_path)
            crawl_obj = Crawl.objects.order_by("-created_at").first()
            crawl = (crawl_obj.max_depth, crawl_obj.tags_str, crawl_obj.notes, crawl_obj.config) if crawl_obj else None
            snapshot_rows = list(Snapshot.objects.order_by("depth", "url").values_list("url", "depth", "status", "parent_snapshot_id"))
            archive_results = list(
                ArchiveResult.objects.order_by("plugin", "status").values_list("plugin", "status", "output_files", "output_size"),
            )

        assert crawl[:3] == (2, "web-depth-two", "created from running-server web ui")
        assert (crawl[3] or {})["CRAWL_MAX_URLS"] == 20
        assert depth_counts.get(0, 0) >= 1
        assert depth_counts.get(1, 0) >= len(recursive_test_site["child_urls"])
        assert depth_counts.get(2, 0) >= len(recursive_test_site["deep_urls"])
        assert max(depth_counts) <= 2
        assert set(recursive_test_site["child_urls"]).issubset({url for url, depth, _status, _parent in snapshot_rows if depth == 1})
        assert set(recursive_test_site["deep_urls"]).issubset({url for url, depth, _status, _parent in snapshot_rows if depth == 2})

        result_statuses = [(plugin, status) for plugin, status, _files, _size in archive_results]
        assert ("wget", "succeeded") in result_statuses
        assert any(plugin.endswith("parse_html_urls") and status == "succeeded" for plugin, status in result_statuses)
        assert len([status for _plugin, status, _files, _size in archive_results if status == "failed"]) <= 2
        assert list((tmp_path / "archive/users").rglob("snapshots/**/parse_html_urls/**/urls.jsonl"))
        assert list((tmp_path / "archive/users").rglob("snapshots/**/wget/**/*.html"))

        progress = session.get(
            f"http://127.0.0.1:{port}/progress.json",
            headers={"Host": f"admin.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert progress.status_code == 200
        assert "active_crawls" in progress.json()

        index_page = requests.get(
            f"http://web.archivebox.localhost:{port}/",
            timeout=10,
        )
        assert index_page.status_code == 200
        assert recursive_test_site["root_url"] in index_page.text

        snapshot_admin = session.get(
            f"http://admin.archivebox.localhost:{port}/admin/core/snapshot/",
            timeout=10,
        )
        assert snapshot_admin.status_code == 200
        assert recursive_test_site["root_url"] in snapshot_admin.text
    finally:
        stop_server(tmp_path)
