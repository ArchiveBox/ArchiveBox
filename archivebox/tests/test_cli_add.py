#!/usr/bin/env python3
"""
Comprehensive tests for archivebox add command.
Verify add creates snapshots in DB, crawls, source files, and archive directories.
"""

import os
import json

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
from archivebox.workers.models import RETRY_AT_MAX
from archivebox.tests.conftest import _find_system_browser, find_snapshot_dir, run_archivebox_cmd, run_queued_crawls, cli_env

from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_add_single_url_records_url_in_crawl(initialized_archive):
    """Test that adding a single URL queues a crawl with the submitted URL."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()

    assert crawl.get_urls_list() == ["https://example.com"]


def test_add_bg_queues_crawl_without_creating_snapshots(initialized_archive):
    """Background add should leave root snapshot creation to the runner."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--bg", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot_count = Snapshot.objects.count()

    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is not None
    assert snapshot_count == 0


def test_add_index_only_rejected_urls_leave_empty_crawl_for_runner_to_seal(initialized_archive):
    """Index-only add only creates the crawl; rejected URLs are sealed by the runner."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        [
            "add",
            "--index-only",
            "--depth=0",
            "--url-denylist=example.com",
            "https://example.com",
        ],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot_count = Snapshot.objects.count()

    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is None
    assert snapshot_count == 0

    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot_count = Snapshot.objects.count()

    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None
    assert snapshot_count == 0


def test_add_index_only_rejects_archivebox_internal_urls(initialized_archive):
    """Index-only add must apply the same internal URL guard as snapshot creation."""
    env = cli_env(disable_extractors=True)
    internal_urls = [
        "http://archivebox.localhost:9292/admin/",
        "http://web.archivebox.localhost:9292/",
        "http://api.archivebox.localhost:9292/api/v1/docs",
        "http://snap-2fb8e923c58c.archivebox.localhost:9292/index.html",
    ]
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", *internal_urls],
        cwd=initialized_archive,
        env={**env, "BASE_URL": "http://archivebox.localhost:9292"},
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot_count = Snapshot.objects.count()

    assert crawl.get_urls_list() == []
    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is None
    assert snapshot_count == 0


def test_add_creates_crawl_record(initialized_archive):
    """Test that add command creates a Crawl record in the database."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    with use_archivebox_db(initialized_archive):
        crawl_count = Crawl.objects.count()

    assert crawl_count == 1


def test_add_creates_source_file(initialized_archive):
    """Test that add creates a source file with the URL."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    sources_dir = initialized_archive / "sources"
    assert sources_dir.exists()

    source_files = list(sources_dir.glob("*cli_add.txt"))
    assert len(source_files) >= 1

    source_content = source_files[0].read_text()
    assert "https://example.com" in source_content


def test_add_multiple_urls_single_command(initialized_archive):
    """Test adding multiple URLs in a single command records one crawl."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com", "https://example.org"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()

    assert crawl.get_urls_list() == ["https://example.com", "https://example.org"]


def test_add_from_file(initialized_archive):
    """Test adding URLs from a file.

    The add command should treat a file argument as URL input and queue
    a crawl containing each URL.
    """

    env = cli_env(disable_extractors=True)
    # Create a file with URLs
    urls_file = initialized_archive / "urls.txt"
    urls_file.write_text("https://example.com\nhttps://example.org\n")

    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", str(urls_file)],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl_count = Crawl.objects.count()
        urls = Crawl.objects.get().get_urls_list()

    # The file is parsed into two input URLs.
    assert crawl_count == 1
    assert urls == ["https://example.com", "https://example.org"]


def test_add_with_depth_0_flag(initialized_archive):
    """Test that --depth=0 flag is accepted and works."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0
    assert "unrecognized arguments: --depth" not in result.stderr


def test_add_with_depth_1_flag(initialized_archive):
    """Test that --depth=1 flag is accepted."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=1", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0
    assert "unrecognized arguments: --depth" not in result.stderr


def test_add_rejects_invalid_depth_values(initialized_archive):
    """Test that add rejects depth values outside the supported range."""
    env = cli_env(disable_extractors=True)

    for depth in ("5", "-1"):
        result = run_archivebox_cmd(
            ["add", "--index-only", f"--depth={depth}", "https://example.com"],
            cwd=initialized_archive,
            env=env,
        )
        stderr = result.stderr.lower()
        assert result.returncode != 0
        assert "invalid" in stderr or "not one of" in stderr


def test_add_with_tags(initialized_archive):
    """Test adding URL with tags stores tags_str in crawl.

    With --index-only, Tag objects are not created until archiving happens.
    Tags are stored as a string in the Crawl.tags_str field.
    """
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "--tag=test,example", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    with use_archivebox_db(initialized_archive):
        tags_str = Crawl.objects.values_list("tags_str", flat=True).get()

    # Tags are stored as a comma-separated string in crawl
    assert "test" in tags_str or "example" in tags_str


def test_add_records_selected_persona_on_crawl(initialized_archive):
    """Test add persists the selected persona so browser config derives from it later."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "--persona=Default", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()

    assert crawl.persona_id
    assert "ACTIVE_PERSONA" not in crawl.config
    assert (initialized_archive / "personas" / "Default" / "chrome_profile").is_dir()


def test_add_records_url_filter_overrides_on_crawl(initialized_archive):
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        [
            "add",
            "--index-only",
            "--depth=0",
            "--domain-allowlist=example.com,*.example.com",
            "--domain-denylist=static.example.com",
            "https://example.com",
        ],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()

    assert crawl.config["URL_ALLOWLIST"] == "example.com,*.example.com"
    assert crawl.config["URL_DENYLIST"] == "static.example.com"
    assert not (initialized_archive / "personas" / "Default" / "chrome_extensions").exists()


def test_add_duplicate_url_creates_separate_crawls(initialized_archive):
    """Test that adding the same URL twice creates separate crawls.

    Each 'add' command creates a new Crawl. Multiple crawls can archive the same URL.
    This allows re-archiving URLs at different times.
    """

    env = cli_env(disable_extractors=True)
    # Add URL first time
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    # Add same URL second time with --update to opt out of ONLY_NEW.
    run_archivebox_cmd(
        ["add", "--index-only", "--update", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    with use_archivebox_db(initialized_archive):
        crawl_count = Crawl.objects.count()
        crawl_urls = list(Crawl.objects.order_by("created_at").values_list("urls", flat=True))

    # Each add creates a new crawl with its own queued work.
    assert crawl_count == 2
    assert crawl_urls == ["https://example.com", "https://example.com"]


def test_add_with_overwrite_flag(initialized_archive):
    """Test that --overwrite flag forces re-archiving."""
    env = cli_env(disable_extractors=True)

    # Add URL first time
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    # Add with overwrite
    result = run_archivebox_cmd(
        ["add", "--index-only", "--overwrite", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0
    assert "unrecognized arguments: --overwrite" not in result.stderr


def test_snapshot_create_creates_current_output_directory(initialized_archive):
    """Test the user-facing snapshot creation path creates an output directory."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )

    with use_archivebox_db(initialized_archive):
        snapshot_id = str(Snapshot.objects.values_list("id", flat=True).get())

    snapshot_dir = find_snapshot_dir(initialized_archive, snapshot_id)
    assert snapshot_dir is not None, f"Snapshot output directory not found for {snapshot_id}"
    assert snapshot_dir.is_dir()


def test_add_help_shows_depth_and_tag_options(initialized_archive):
    """Test that add --help documents the main filter and crawl options."""

    result = run_archivebox_cmd(
        ["add", "--help"],
    )

    assert result.returncode == 0
    assert "--depth" in result.stdout
    assert "--max-urls" in result.stdout
    assert "--crawl-max-size" in result.stdout
    assert "--crawl-timeout" in result.stdout
    assert "--snapshot-max-size" in result.stdout
    assert "--tag" in result.stdout


def test_add_records_max_url_and_size_limits_on_crawl(initialized_archive):
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        [
            "add",
            "--index-only",
            "--depth=1",
            "--max-urls=3",
            "--crawl-max-size=45mb",
            "--crawl-timeout=120",
            "--snapshot-max-size=5mb",
            "https://example.com",
        ],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    columns = {field.name for field in Crawl._meta.local_fields}
    with use_archivebox_db(initialized_archive):
        config = Crawl.objects.values_list("config", flat=True).get() or {}

    assert {"max_urls", "crawl_max_size", "crawl_timeout", "snapshot_max_size"}.isdisjoint(columns)
    assert config["CRAWL_MAX_URLS"] == 3
    assert config["CRAWL_MAX_SIZE"] == 45 * 1024 * 1024
    assert config["CRAWL_TIMEOUT"] == 120
    assert config["SNAPSHOT_MAX_SIZE"] == 5 * 1024 * 1024


def test_add_without_args_shows_usage(initialized_archive):
    """Test that add without URLs fails with a usage hint instead of crashing."""

    result = run_archivebox_cmd(
        ["add"],
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "usage" in combined.lower() or "url" in combined.lower()


def test_add_index_only_queues_crawl_without_starting_runner(initialized_archive):
    """Test that --index-only creates only a queued crawl and returns fast."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        timeout=30,  # Should be fast
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot_count = Snapshot.objects.count()

    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is None
    assert snapshot_count == 0


def test_add_index_only_leaves_snapshot_creation_to_runner(initialized_archive):
    """Test that index-only add does not create snapshots before the runner."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    with use_archivebox_db(initialized_archive):
        crawl_id = Crawl.objects.values_list("id", flat=True).get()
        snapshot_count = Snapshot.objects.count()

    assert crawl_id
    assert snapshot_count == 0


@pytest.mark.parametrize("bg", [False, True], ids=["foreground", "bg"])
def test_add_paused_creates_paused_crawl_without_running_runner(initialized_archive, bg):
    """--paused should create a PAUSED crawl and return immediately without the
    orchestrator running, in both foreground and --bg mode."""
    env = cli_env(disable_extractors=True)
    cmd = ["add", "--paused", "--depth=0", "https://example.com"]
    if bg:
        cmd.insert(1, "--bg")

    result = run_archivebox_cmd(
        cmd,
        cwd=initialized_archive,
        env=env,
        timeout=30,  # Must return immediately - the runner never starts
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot_count = Snapshot.objects.count()

    # Crawl is parked in the PAUSED state with a far-future retry_at, exactly
    # like the /add/ web form's start_paused option, so no worker claims it.
    assert crawl.status == Crawl.StatusChoices.PAUSED
    assert crawl.retry_at == RETRY_AT_MAX
    assert crawl.get_urls_list() == ["https://example.com"]

    # The orchestrator never ran: no snapshots were created from the crawl URLs.
    assert snapshot_count == 0


def test_snapshot_create_sets_snapshot_timestamp(initialized_archive):
    """Test the user-facing snapshot creation path sets a timestamp."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )

    with use_archivebox_db(initialized_archive):
        timestamp = Snapshot.objects.values_list("timestamp", flat=True).get()

    assert timestamp is not None
    assert len(str(timestamp)) > 0


@pytest.mark.timeout(180)
def test_cli_add_real_urls_with_options_writes_inspectable_outputs(initialized_archive):

    wget_urls = [
        "https://example.com",
        "https://pirate.github.io/stress-tests/challenge.html",
    ]
    chrome_url = "https://example.com/?archivebox-chrome-flow=1"
    env = os.environ.copy()
    env.pop("CHROME_BINARY", None)
    env.update(
        {
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "TIMEOUT": "60",
            "SAVE_WGET": "true",
            "SAVE_HEADERS": "false",
            "SAVE_TITLE": "false",
            "SAVE_READABILITY": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_MERCURY": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_PDF": "false",
            "SAVE_DOM": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_FAVICON": "false",
        },
    )
    _cmd_result = run_archivebox_cmd(
        [
            "add",
            "--depth=0",
            "--max-urls=2",
            "--crawl-max-size=10mb",
            "--tag=real-flow,challenge",
            "--parser=url_list",
            "--plugins=wget",
            *wget_urls,
        ],
        cwd=initialized_archive,
        env=env,
        timeout=180,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout

    chrome_env = env | {
        "SAVE_WGET": "false",
        "SAVE_HEADERS": "true",
        "SAVE_TITLE": "true",
        "CHROME_HEADLESS": "true",
        "CHROME_SANDBOX": "false",
        "CHROME_ISOLATION": "snapshot",
    }
    system_browser = _find_system_browser()
    if system_browser:
        chrome_env["CHROME_BINARY"] = str(system_browser)
    _cmd_result = run_archivebox_cmd(
        ["install", "chrome"],
        cwd=initialized_archive,
        env=chrome_env,
        timeout=600,
    )
    install_stdout, install_stderr, install_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert install_returncode == 0, install_stderr or install_stdout
    _cmd_result = run_archivebox_cmd(
        [
            "add",
            "--depth=0",
            "--max-urls=1",
            "--crawl-max-size=10mb",
            "--tag=chrome-flow",
            "--parser=url_list",
            "--plugins=chrome,wget,headers,title",
            chrome_url,
        ],
        cwd=initialized_archive,
        env=chrome_env,
        timeout=180,
    )
    chrome_stdout, chrome_stderr, chrome_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert chrome_returncode == 0, chrome_stderr or chrome_stdout

    _cmd_result = run_archivebox_cmd(
        ["list", "--tag=real-flow"],
        cwd=initialized_archive,
        env=env,
        timeout=60,
    )
    list_stdout, list_stderr, list_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert list_returncode == 0, list_stderr or list_stdout
    listed = [json.loads(line) for line in list_stdout.splitlines() if line.strip()]
    assert {item["url"] for item in listed} >= set(wget_urls)

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.order_by("-created_at").values_list("max_depth", "tags_str", "config").first()
        real_flow_crawl = Crawl.objects.filter(tags_str="real-flow,challenge").values_list("max_depth", "tags_str", "config").first()
        snapshots = list(Snapshot.objects.order_by("url").values_list("id", "url", "depth", "status", "title"))
        archive_results = list(
            ArchiveResult.objects.select_related("snapshot")
            .order_by("snapshot__url", "plugin")
            .values_list("snapshot__url", "plugin", "status", "output_files", "output_size", "output_str"),
        )
        processes = list(Process.objects.filter(process_type="hook").values_list("process_type", "status", "exit_code", "pwd", "cmd"))

    assert real_flow_crawl is not None
    assert real_flow_crawl[0] == 0
    assert real_flow_crawl[1] == "real-flow,challenge"
    real_flow_config = real_flow_crawl[2] or {}
    assert real_flow_config["CRAWL_MAX_URLS"] == 2
    assert real_flow_config["CRAWL_MAX_SIZE"] == 10 * 1024 * 1024
    assert real_flow_config.get("SNAPSHOT_MAX_SIZE", 0) == 0
    assert "wget" in real_flow_config["PLUGINS"]
    assert crawl is not None
    assert crawl[1] == "chrome-flow"
    assert "wget,headers,title" in json.dumps(crawl[2] or {})

    snapshot_urls = {url for _id, url, _depth, _status, _title in snapshots}
    assert snapshot_urls >= {*wget_urls, chrome_url}
    assert all(depth == 0 for _id, _url, depth, _status, _title in snapshots)

    by_url_plugin = {(url, plugin): status for url, plugin, status, _files, _size, _output in archive_results}
    assert by_url_plugin[("https://example.com", "wget")] == "succeeded"
    assert by_url_plugin[("https://pirate.github.io/stress-tests/challenge.html", "wget")] == "succeeded"
    assert by_url_plugin[(chrome_url, "headers")] == "succeeded"
    assert by_url_plugin[(chrome_url, "title")] == "succeeded"
    unexpected_results = [
        (url, plugin, status, output) for url, plugin, status, _files, _size, output in archive_results if status != "succeeded"
    ]
    assert not unexpected_results

    snapshot_root = initialized_archive / "archive/users/system/snapshots"
    html_outputs = [path for path in snapshot_root.rglob("wget/**/*.html") if path.is_file()]
    header_outputs = [path for path in snapshot_root.rglob("headers/**/headers.json") if path.is_file() and path.stat().st_size > 0]
    title_outputs = [path for path in snapshot_root.rglob("title/title.txt") if path.is_file() and path.stat().st_size > 0]
    index_outputs = [path for path in snapshot_root.rglob("index.jsonl") if path.is_file()]
    assert html_outputs
    assert header_outputs
    assert any("example.com" in path.read_text(errors="ignore").lower() for path in header_outputs)
    assert title_outputs
    assert any("Example Domain" in path.read_text(errors="ignore") for path in title_outputs)
    assert len(index_outputs) >= len(wget_urls) + 1

    combined_html = "\n".join(path.read_text(errors="ignore") for path in html_outputs)
    assert "Example Domain" in combined_html
    assert "Browser Agent Challenge for AI Browser Drivers" in combined_html

    assert processes
    assert any("wget" in (pwd or "") or "wget" in (cmd or "") for _type, _status, _exit, pwd, cmd in processes)
    assert any("headers" in (pwd or "") or "headers" in (cmd or "") for _type, _status, _exit, pwd, cmd in processes)


@pytest.mark.timeout(180)
def test_cli_recursive_crawl_processes_discovered_html_urls(initialized_archive, recursive_test_site):

    env = os.environ.copy()
    env.update(
        {
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "TIMEOUT": "60",
            "SAVE_WGET": "true",
            "SAVE_HEADERS": "false",
            "SAVE_TITLE": "false",
            "SAVE_READABILITY": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_MERCURY": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_PDF": "false",
            "SAVE_DOM": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_FAVICON": "false",
            "PARSE_HTML_URLS_ENABLED": "true",
            "PARSE_DOM_OUTLINKS_ENABLED": "false",
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
        },
    )
    root_url = recursive_test_site["root_url"]
    child_url = recursive_test_site["child_urls"][0]

    _cmd_result = run_archivebox_cmd(
        [
            "add",
            "--depth=2",
            "--max-urls=2",
            "--crawl-max-size=50mb",
            "--tag=recursive-flow",
            "--parser=url_list",
            "--plugins=wget,parse_html_urls",
            root_url,
        ],
        cwd=initialized_archive,
        env=env,
        timeout=180,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.order_by("-created_at").values_list("max_depth", "tags_str", "config").first()
        snapshots = list(Snapshot.objects.order_by("depth", "url").values_list("url", "depth", "status"))
        archive_results = list(
            ArchiveResult.objects.select_related("snapshot")
            .order_by("snapshot__depth", "snapshot__url", "plugin")
            .values_list("snapshot__url", "plugin", "status", "output_files"),
        )

    assert crawl[0] == 2
    assert crawl[1] == "recursive-flow"
    crawl_config = crawl[2] or {}
    assert crawl_config["CRAWL_MAX_URLS"] == 2
    assert crawl_config["CRAWL_MAX_SIZE"] == 50 * 1024 * 1024
    assert crawl_config.get("SNAPSHOT_MAX_SIZE", 0) == 0
    assert (root_url, 0, "sealed") in snapshots
    assert any(url == child_url and depth == 1 and status == "sealed" for url, depth, status in snapshots)

    by_url_plugin = {(url, plugin): status for url, plugin, status, _files in archive_results}
    assert by_url_plugin[(root_url, "wget")] == "succeeded"
    assert by_url_plugin[(root_url, "parse_html_urls")] == "succeeded"
    assert by_url_plugin[(child_url, "wget")] == "succeeded"

    urls_outputs = list((initialized_archive / "archive/users/system/snapshots").rglob("parse_html_urls/urls.jsonl"))
    assert urls_outputs
    assert any(child_url in path.read_text() for path in urls_outputs)
