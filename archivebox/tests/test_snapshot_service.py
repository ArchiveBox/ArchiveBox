import json
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db
from .conftest import (
    cli_env,
    get_free_port,
    init_archive,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _snapshot_state(cwd: Path, url: str) -> dict[str, object]:
    with use_archivebox_db(cwd):
        snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by").get(url=url)
        snapshot_dir = Path(snapshot.output_dir)
        crawl_dir = Path(snapshot.crawl.output_dir)
        crawl_link = crawl_dir / "snapshots" / Snapshot.extract_domain_from_url(snapshot.url) / str(snapshot.id)
        results = list(
            ArchiveResult.objects.filter(snapshot=snapshot)
            .order_by("plugin", "hook_name")
            .values("plugin", "hook_name", "status", "output_files", "output_size"),
        )
        return {
            "id": str(snapshot.id),
            "crawl_id": str(snapshot.crawl_id),
            "status": snapshot.status,
            "retry_at": snapshot.retry_at,
            "downloaded_at": snapshot.downloaded_at,
            "output_size": snapshot.output_size,
            "snapshot_dir": snapshot_dir,
            "crawl_dir": crawl_dir,
            "crawl_link": crawl_link,
            "results": results,
        }


@pytest.mark.timeout(180)
def test_snapshot_service_cli_add_seals_snapshot_and_writes_indexes(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True, PLUGINS="wget", SAVE_WGET="True")
    _cmd_result = run_archivebox_cmd(
        ["add", "--depth=0", "--plugins=wget", recursive_test_site["root_url"]],
        cwd=tmp_path,
        env=env,
        timeout=180,
    )
    stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert code == 0, f"archivebox add failed with code {code}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

    state = _snapshot_state(tmp_path, recursive_test_site["root_url"])
    snapshot_dir = state["snapshot_dir"]
    crawl_link = state["crawl_link"]
    assert isinstance(snapshot_dir, Path)
    assert isinstance(crawl_link, Path)

    assert state["status"] == Snapshot.StatusChoices.SEALED
    assert state["retry_at"] is None
    assert state["downloaded_at"] is not None
    assert snapshot_dir.is_dir()
    assert crawl_link.is_symlink()
    assert crawl_link.resolve() == snapshot_dir.resolve()

    index_jsonl = snapshot_dir / "index.jsonl"
    assert index_jsonl.is_file()

    records = [json.loads(line) for line in index_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records[0]["type"] == "Snapshot"
    assert records[0]["id"] == state["id"]
    assert any(record.get("type") == "ArchiveResult" and record.get("plugin") == "wget" for record in records)

    wget_files = [path for path in (snapshot_dir / "wget").rglob("*") if path.is_file()]
    assert wget_files
    assert any("Root" in path.read_text(encoding="utf-8", errors="ignore") for path in wget_files if path.suffix in (".html", ".txt"))
    assert any(result["plugin"] == "wget" and result["status"] == ArchiveResult.StatusChoices.SUCCEEDED for result in state["results"])
