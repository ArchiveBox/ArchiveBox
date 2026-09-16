import pytest
import subprocess
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
    run_archivebox_cmd,
    run_queued_crawls,
    start_archivebox_server,
    stop_archivebox_process,
    stop_server,
    get_http_response,
    wait_for_log,
)
from archivebox.core.models import Snapshot, SnapshotTag
from archivebox.crawls.models import Crawl
from archivebox.tests.test_orm_helpers import use_archivebox_db

from archivebox.tests.test_import_helpers import (
    IMPORT_FORMAT_EXPECTATIONS,
    assert_expected_import_snapshots,
    assert_no_file_or_shell_payload_snapshots,
    malicious_add_inputs,
    write_import_format_files,
)

pytestmark = pytest.mark.django_db(transaction=True)


IMPORT_FORMAT_ENV = {
    "USE_COLOR": "False",
    "SHOW_PROGRESS": "False",
    "PLUGINS": "parse_html_urls,parse_jsonl_urls,parse_netscape_urls,parse_rss_urls,parse_txt_urls",
    "USE_CHROME": "False",
    "URL_ALLOWLIST": r"example\.com|example\.org|iana\.org|www\.iana\.org",
}


def start_api_server_without_runner(cwd: Path, env: dict[str, str], port: int):
    log_path = cwd / "api-server.log"
    log = log_path.open("w", encoding="utf-8")
    process = run_archivebox_cmd(
        ["manage", "runserver", f"127.0.0.1:{port}", "--noreload"],
        cwd=cwd,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        wait=False,
        start_new_session=True,
    )
    log.close()
    wait_for_log(log_path, "Listening on TCP", timeout=30)
    get_http_response(port, host=f"api.archivebox.localhost:{port}", path="/api/v1/docs")
    return process


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
    assert crawl.urls == submitted_url
    assert Snapshot.objects.count() == 0


def test_api_cli_add_filters_invalid_items_from_multi_url_batch(client, tmp_path, api_headers):
    init_archive(tmp_path)
    submitted_url = "https://example.com/api-cli-add-valid-batch-item"

    response = api_client_request(
        client,
        "post",
        "/api/v1/cli/add",
        payload={
            "urls": [submitted_url, "not a URL", "https://example.org\nhttps://example.net"],
            "plugins": "__archivebox_test_no_plugins__",
            "index_only": True,
        },
        headers=api_headers,
    )

    assert response.status_code == 200, response.content
    assert response.json()["result"]["queued_urls"] == [submitted_url]
    assert Crawl.objects.get().urls == submitted_url


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

    assert crawls == sorted(submitted_urls)


@pytest.mark.timeout(360)
def test_api_cli_add_import_text_formats_preserve_metadata_and_crawl_inner_urls(tmp_path):
    """REST API add should accept rich import text and queue real inner URLs with metadata preserved."""
    init_archive(tmp_path)
    import_files = write_import_format_files(tmp_path)
    expected_urls = {case["url"] for case in IMPORT_FORMAT_EXPECTATIONS.values()}
    port = get_free_port()
    env = cli_env(port=port, server=True, **IMPORT_FORMAT_ENV)
    api_token = create_admin_and_token(tmp_path)

    api_server = start_api_server_without_runner(tmp_path, env, port)
    try:
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

        stop_archivebox_process(api_server)
        api_server = None
        run_queued_crawls(tmp_path, env=env, timeout=240)
        with use_archivebox_db(tmp_path):
            for crawl in Crawl.objects.all():
                assert not crawl.snapshot_set.filter(url__startswith="archivebox://").exists()
                root_input = (crawl.output_dir / "input" / "staticfile" / "stdin.txt").read_text(encoding="utf-8")
                assert root_input == crawl.urls
        api_server = start_api_server_without_runner(tmp_path, env, port)
        assert_expected_import_snapshots(tmp_path, expected_urls)

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
        if api_server is not None:
            stop_archivebox_process(api_server)

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

    api_server = start_api_server_without_runner(tmp_path, env, port)
    try:
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

        stop_archivebox_process(api_server)
        api_server = None
        run_queued_crawls(tmp_path, env=env, timeout=120)
    finally:
        if api_server is not None:
            stop_archivebox_process(api_server)

    assert_expected_import_snapshots(tmp_path, {safe_url}, expected_tags={"api-security"})
    assert_no_file_or_shell_payload_snapshots(tmp_path, canary=canary)
    with use_archivebox_db(tmp_path):
        snapshot = Snapshot.objects.get(url=safe_url)
        crawl = Crawl.objects.get()
    assert crawl.status in {Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED, Crawl.StatusChoices.SEALED}
    assert snapshot.status in {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
    with use_archivebox_db(tmp_path):
        tag_names = set(SnapshotTag.objects.filter(snapshot=snapshot).values_list("tag__name", flat=True))
    assert "api-security" in tag_names
