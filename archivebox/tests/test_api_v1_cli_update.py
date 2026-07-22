import pytest

from .conftest import (
    api_client_request,
    cli_env,
    create_admin_and_token,
    get_free_port,
    init_archive,
    live_api_request,
    parse_jsonl_output,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_server,
    wait_for_live_api,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_cli_update_api_accepts_empty_json_without_traceback(client, tmp_path, api_headers):
    init_archive(tmp_path)

    try:
        response = api_client_request(
            client,
            "post",
            "/api/v1/cli/update",
            payload={},
            headers=api_headers,
        )
    finally:
        stop_server(tmp_path)

    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["success"] is True
    assert "Traceback" not in response.content.decode()


@pytest.mark.timeout(180)
def test_cli_update_api_supports_all_snapshot_list_filters_with_real_rows(tmp_path):
    from archivebox.core.models import Snapshot
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(disable_extractors=True)
    init_archive(tmp_path)

    rows = (
        ("https://alpha.example.com/articles/needle", "Needle Alpha", "api-keep", "1700000000", "2023-11-14T22:13:20+00:00"),
        ("https://beta.example.org/posts/haystack", "Haystack Beta", "api-other", "1710000000", "2024-03-09T16:00:00+00:00"),
        ("https://docs.archivebox.io/manual", "Manual Gamma", "api-docs", "1720000000", "2024-07-03T09:46:40+00:00"),
    )
    for url, _title, tag, _timestamp, _bookmarked_at in rows:
        run_archivebox_cmd(["snapshot", "create", f"--tag={tag}", url], cwd=tmp_path, env=env, check=True)
    with use_archivebox_db(tmp_path):
        for url, title, _tag, timestamp, bookmarked_at in rows:
            Snapshot.objects.filter(url=url).update(title=title, timestamp=timestamp, bookmarked_at=bookmarked_at)
    list_result = run_archivebox_cmd(["snapshot", "list", "--sort", "timestamp"], cwd=tmp_path, env=env, check=True)
    initial_snapshots = {record["url"]: record for record in parse_jsonl_output(list_result.stdout) if record.get("type") == "Snapshot"}
    alpha = initial_snapshots["https://alpha.example.com/articles/needle"]
    alpha_jsonl = next(line for line in list_result.stdout.splitlines() if alpha["id"] in line) + "\n"
    run_archivebox_cmd(
        ["snapshot", "update", "--status=paused"],
        cwd=tmp_path,
        stdin=alpha_jsonl,
        env=env,
        check=True,
    )

    port = get_free_port()
    env = {
        **cli_env(port=port, server=True, PUBLIC_INDEX="True"),
        **env,
    }
    api_token = create_admin_and_token(tmp_path)

    def assert_update_filter(label, body, expected_records):
        response = live_api_request(
            port,
            "post",
            "/api/v1/cli/update",
            api_token=api_token,
            json={**body, "batch_size": 100, "migrate_only": True},
            timeout=30,
        )
        assert response.status_code == 200, f"{label}: {response.text}"
        assert "Traceback" not in response.text
        payload = response.json()
        assert payload["success"] is True, label
        expected_ids = {record["id"] for record in expected_records}
        assert set(payload["result"]["snapshot_ids"]) == expected_ids, label
        assert payload["result"]["matched_count"] == len(expected_ids), label

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)
        list_result = run_archivebox_cmd(["snapshot", "list", "--sort", "timestamp"], cwd=tmp_path, env=env, check=True)
        snapshots = {record["url"]: record for record in parse_jsonl_output(list_result.stdout) if record.get("type") == "Snapshot"}
        alpha = snapshots["https://alpha.example.com/articles/needle"]
        beta = snapshots["https://beta.example.org/posts/haystack"]
        gamma = snapshots["https://docs.archivebox.io/manual"]
        status_result = run_archivebox_cmd(
            ["snapshot", "list", "--status", alpha["status"]],
            cwd=tmp_path,
            env=env,
            check=True,
        )
        status_records = [record for record in parse_jsonl_output(status_result.stdout) if record.get("type") == "Snapshot"]

        cases = [
            ("status", {"status": alpha["status"]}, status_records),
            ("filter_type exact", {"filter_type": "exact", "filter_patterns": [alpha["url"]]}, [alpha]),
            ("filter_type substring", {"filter_type": "substring", "filter_patterns": ["needle"]}, [alpha]),
            ("filter_type regex", {"filter_type": "regex", "filter_patterns": [r"alpha\.example\.com/.+needle"]}, [alpha]),
            ("filter_type domain", {"filter_type": "domain", "filter_patterns": ["alpha.example.com"]}, [alpha]),
            ("filter_type tag", {"filter_type": "tag", "filter_patterns": ["api-keep"]}, [alpha]),
            ("filter_type timestamp", {"filter_type": "timestamp", "filter_patterns": [alpha["timestamp"]]}, [alpha]),
            ("url__icontains", {"url__icontains": "needle"}, [alpha]),
            ("url__istartswith", {"url__istartswith": "https://alpha.example.com"}, [alpha]),
            ("tag", {"tag": "api-keep"}, [alpha]),
            ("crawl_id", {"crawl_id": alpha["crawl_id"]}, [alpha]),
            ("limit and sort", {"limit": 1, "sort": "timestamp"}, [alpha]),
            ("search", {"search": "meta", "filter_patterns": ["Needle Alpha"]}, [alpha]),
            ("before", {"before": 1715000000}, [alpha, beta]),
            ("after", {"after": 1715000000}, [gamma]),
            ("resume", {"resume": beta["timestamp"]}, [alpha, beta]),
        ]
        for label, body, expected_records in cases:
            assert_update_filter(label, body, expected_records)
    finally:
        stop_server(tmp_path)
