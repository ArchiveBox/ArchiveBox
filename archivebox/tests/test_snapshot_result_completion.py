"""Native capture completion after an artifact's DB consumer fails."""

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from asgiref.sync import sync_to_async
from django.db import close_old_connections, connection

from abx_dl.events import ArchiveResultEvent, ProcessStartedEvent, SnapshotCompletedEvent
from archivebox.base_models.models import get_or_create_system_user_pk
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
from archivebox.services.runner import CrawlRunner
from archivebox.tests.conftest import resolve_abxpkg_binary_env
from archivebox.tests.test_archive_result_service import _cleanup_machine_process_rows

pytestmark = pytest.mark.django_db(transaction=True)


def test_failed_result_consumer_cannot_seal_snapshot(hermetic_lib_dir):
    from abx_plugins.plugins.base.utils import _collect_required_schema_paths
    from abxpkg import prepare_script_exec_plan
    from archivebox.plugins.discovery import get_plugin_catalog

    plugin = get_plugin_catalog()["hashes"]
    hook = plugin.filter_hooks("Snapshot")[0]
    binary_env = resolve_abxpkg_binary_env(hermetic_lib_dir, deps_from=_collect_required_schema_paths(hook.path.parent / "config.json"))
    assert prepare_script_exec_plan(hook.path, env=binary_env)
    crawl = Crawl.objects.create(
        urls="https://example.com/result-consumer-completion",
        config={"PLUGINS": "hashes", "ABXPKG_LIB_DIR": str(hermetic_lib_dir)},
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    snapshot_dir = Path(snapshot.output_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    source = snapshot_dir / "source.txt"
    source.write_text("Actual native hash input.\n" * 10000)
    db_path = connection.settings_dict["NAME"]
    assert Path(db_path).is_file()
    runner = CrawlRunner(crawl, snapshot_ids=[str(snapshot.id)], selected_plugins=["hashes"], show_progress=False)

    completed_events = []

    def observe_completed(event):
        completed_events.append(event)

    runner.bus.on(SnapshotCompletedEvent, observe_completed)

    async def run():
        writer = await asyncio.to_thread(sqlite3.connect, db_path, check_same_thread=False)
        task = asyncio.create_task(runner.run())
        try:
            started = await runner.bus.find(ProcessStartedEvent, plugin_name="hashes", hook_name=hook.name, past=True, future=60)
            assert started is not None
            await started.wait()
            await started.event_results_list()
            # Block the real result write only after the running row is durable.
            # Neither the bus deadline nor SQLite's bounded lock policy changes.
            await asyncio.to_thread(writer.execute, "BEGIN IMMEDIATE")
            try:
                result_event = await runner.bus.find(ArchiveResultEvent, child_of=started, past=True, future=60)
                assert result_event is not None
                await result_event.now()

            finally:
                await asyncio.to_thread(writer.rollback)
            # Release after the actual event deadline so unrelated lease writes
            # are not another source of failure. A running synchronous write can
            # finish late, but cannot retroactively complete its failed consumer.
            await sync_to_async(close_old_connections, thread_sensitive=True)()
            with pytest.raises(Exception):
                await task
            with pytest.raises(Exception, match="ArchiveResult"):
                await result_event.event_results_list()
            assert not completed_events
        finally:
            await asyncio.to_thread(writer.rollback)
            await asyncio.to_thread(writer.close)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(run())
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        result = snapshot.archiveresult_set.get(plugin="hashes", hook_name=hook.name)
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert result.end_ts is not None
        process = Process.objects.get(pk=result.process_id)
        assert process.exit_code == 0
        assert process.status == Process.StatusChoices.EXITED
        hashes = json.loads((snapshot_dir / "hashes" / "hashes.json").read_text())
        assert any(
            item["path"] == "source.txt" and item["hash"] == hashlib.sha256(source.read_bytes()).hexdigest() for item in hashes["files"]
        )
        records = [json.loads(line) for line in (snapshot_dir / "index.jsonl").read_text().splitlines() if line.strip()]
        assert any(record.get("type") == "ArchiveResult" and record["status"] == "succeeded" for record in records)
        assert any(record.get("type") == "Process" and record["exit_code"] == 0 for record in records)
    finally:
        _cleanup_machine_process_rows()
