"""Filesystem-heavy persona preparation must not hold unrelated result writes."""

import asyncio
import hashlib
import json
import time
from pathlib import Path

import pytest

from archivebox.base_models.models import get_or_create_system_user_pk
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.services.runner import CrawlRunner
from archivebox.tests.test_archive_result_service import _cleanup_machine_process_rows, _create_snapshot, _run_shipped_snapshot_hook

pytestmark = pytest.mark.django_db(transaction=True)


def test_persona_copy_does_not_block_another_hooks_result(cached_abxpkg_lib_dir):
    from abx_plugins.plugins.base.utils import _collect_required_schema_paths
    from abxpkg import prepare_script_exec_plan
    from archivebox.plugins.discovery import get_plugin_catalog
    from archivebox.tests.conftest import resolve_abxpkg_binary_env

    hook = get_plugin_catalog()["hashes"].filter_hooks("Snapshot")[0]
    binary_env = resolve_abxpkg_binary_env(
        cached_abxpkg_lib_dir,
        deps_from=_collect_required_schema_paths(hook.path.parent / "config.json"),
    )
    assert prepare_script_exec_plan(hook.path, env=binary_env)
    persona = Persona.objects.create(name="LargeProfile")
    profile = Path(persona.CHROME_USER_DATA_DIR)
    # IndexedDB data is retained profile state, unlike excluded browser caches.
    # Many real files exercise the normal copy/cleanup metadata workload; no
    # injected delay or substitute filesystem/handler supplies the contention.
    data_dir = profile / "Default" / "IndexedDB" / "https_example.com_0.indexeddb.leveldb"
    data_dir.mkdir(parents=True)
    content = b"Retained browser profile data.\n" * 32
    for index in range(30000):
        (data_dir / f"{index:06d}.ldb").write_bytes(content)
    crawl = Crawl.objects.create(
        urls="https://example.com/profile-preparation",
        persona=persona,
        config={"CHROME_ISOLATION": "snapshot", "PLUGINS": "hashes"},
        created_by_id=get_or_create_system_user_pk(),
    )
    preparing_snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    runner = CrawlRunner(crawl, show_progress=False)
    snapshot = _create_snapshot()
    source = Path(snapshot.output_dir) / "source.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("Actual independent captured content.\n" * 1000)

    async def run():
        started = time.monotonic()
        preparing = asyncio.create_task(runner.load_snapshot_payload(str(preparing_snapshot.id)))
        try:
            process, result = await asyncio.to_thread(
                _run_shipped_snapshot_hook,
                snapshot,
                plugin="hashes",
                hook_name=hook.name,
                lib_dir=cached_abxpkg_lib_dir,
            )
            result_elapsed = time.monotonic() - started
            still_preparing = not preparing.done()
            payload = await preparing
            preparation_elapsed = time.monotonic() - started
            print(f"Native result projected in {result_elapsed:.3f}s; profile preparation {preparation_elapsed:.3f}s")
            assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
            assert process.exit_code == 0
            assert still_preparing, "Another capture's filesystem preparation blocked the real hook result"
            return payload
        finally:
            await asyncio.gather(preparing, return_exceptions=True)
            await runner.bus.destroy(clear=False)

    try:
        payload = asyncio.run(run())
        copied = Path(payload["config"]["PERSONAS_DIR"]) / persona.name / "chrome_profile" / data_dir.relative_to(profile)
        assert len(list(copied.glob("*.ldb"))) == 30000
        assert (copied / "029999.ldb").read_bytes() == content
        result = snapshot.archiveresult_set.get(plugin="hashes", hook_name=hook.name)
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
        hashes = json.loads((Path(snapshot.output_dir) / "hashes" / "hashes.json").read_text())
        assert any(
            item["path"] == "source.txt" and item["hash"] == hashlib.sha256(source.read_bytes()).hexdigest() for item in hashes["files"]
        )
    finally:
        _cleanup_machine_process_rows()
