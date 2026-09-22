from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db
from .conftest import cli_env, get_free_port, init_archive

pytestmark = pytest.mark.django_db(transaction=True)


def _crawl_state(cwd: Path, crawl_id: str) -> dict[str, object]:
    with use_archivebox_db(cwd):
        crawl = Crawl.objects.select_related("created_by").get(id=crawl_id)
        snapshots = list(
            Snapshot.objects.filter(crawl=crawl)
            .order_by("depth", "url")
            .values("id", "url", "depth", "status", "parent_snapshot_id", "downloaded_at"),
        )
        results = list(
            ArchiveResult.objects.filter(snapshot__crawl=crawl)
            .order_by("snapshot__url", "plugin", "hook_name")
            .values("snapshot__url", "plugin", "hook_name", "status", "output_files", "output_size"),
        )
        return {
            "status": crawl.status,
            "retry_at": crawl.retry_at,
            "urls": crawl.urls,
            "config": crawl.config or {},
            "output_dir": Path(crawl.output_dir),
            "snapshots": snapshots,
            "results": results,
        }


@pytest.mark.timeout(240)
def test_crawl_service_run_processes_queued_crawl_and_applies_crawl_config(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(
        port=port,
        PLUGINS="wget,parse_html_urls",
        SAVE_WGET="True",
        SAVE_FAVICON="False",
        SAVE_TITLE="False",
    )
    root_url = recursive_test_site["root_url"]
    about_url = recursive_test_site["child_urls"][0]
    contact_url = recursive_test_site["child_urls"][2]

    _cmd_result = run_archivebox_cmd(
        [
            "add",
            "--bg",
            "--depth=0",
            "--max-urls=20",
            "--plugins=wget,parse_html_urls",
            "--tag=crawl-service-e2e",
            "--url-denylist=/contact$",
            root_url,
            about_url,
            contact_url,
        ],
        cwd=tmp_path,
        env=env,
        timeout=120,
    )
    add_stdout, add_stderr, add_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert add_code == 0, f"archivebox add --bg failed with code {add_code}\nSTDOUT:\n{add_stdout}\nSTDERR:\n{add_stderr}"

    with use_archivebox_db(tmp_path):
        latest_crawl_id = Crawl.objects.order_by("-created_at").values_list("id", flat=True).first()
        assert latest_crawl_id is not None
        crawl_id = str(latest_crawl_id)
    queued_state = _crawl_state(tmp_path, crawl_id)
    assert queued_state["status"] == Crawl.StatusChoices.QUEUED
    assert queued_state["retry_at"] is not None
    assert queued_state["config"]["PLUGINS"] == "wget,parse_html_urls"
    assert queued_state["config"]["URL_DENYLIST"] == "/contact$"
    # add --bg stores the submitted URL list in Crawl.urls and returns; the runner
    # materializes Snapshot rows + applies URL_DENYLIST when it claims the
    # crawl, not at add time. The post-run assertions below verify those.
    assert queued_state["snapshots"] == []

    _cmd_result = run_archivebox_cmd(
        ["run", "--crawl-id", crawl_id],
        cwd=tmp_path,
        env=env,
        timeout=240,
    )
    run_stdout, run_stderr, run_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert run_code == 0, f"archivebox run --crawl-id failed with code {run_code}\nSTDOUT:\n{run_stdout}\nSTDERR:\n{run_stderr}"

    state = _crawl_state(tmp_path, crawl_id)
    snapshots = state["snapshots"]
    results = state["results"]
    snapshotted_urls = {row["url"] for row in snapshots}

    assert state["status"] == Crawl.StatusChoices.SEALED
    assert state["retry_at"] is None
    assert snapshotted_urls == {root_url, about_url}
    assert contact_url not in snapshotted_urls
    assert {row["depth"] for row in snapshots} == {0}
    assert all(row["status"] == Snapshot.StatusChoices.SEALED for row in snapshots)
    assert all(row["downloaded_at"] is not None for row in snapshots)
    assert all("/contact" not in row["url"] for row in snapshots)
    assert all(row["parent_snapshot_id"] is None for row in snapshots)

    result_statuses = {(row["plugin"], row["status"]) for row in results}
    assert ("wget", ArchiveResult.StatusChoices.SUCCEEDED) in result_statuses
    assert any(row["plugin"].endswith("parse_html_urls") and row["status"] == ArchiveResult.StatusChoices.SUCCEEDED for row in results)
    assert any(row["plugin"] == "wget" and row["output_size"] > 0 for row in results)

    assert list((tmp_path / "archive/users/system/snapshots").rglob("wget/**/*.html"))
    assert list((tmp_path / "archive/users/system/snapshots").rglob("parse_html_urls/**/urls.jsonl"))
