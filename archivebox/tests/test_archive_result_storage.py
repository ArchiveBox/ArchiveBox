"""Remote output reads must not hold the shared Django projection executor."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from abx_dl.events import ArchiveResultEvent
from abx_dl.orchestrator import create_bus
from archivebox.core.models import ArchiveResult
from archivebox.services.archive_result_service import ArchiveResultService
from archivebox.tests.test_archive_result_service import (
    _cleanup_machine_process_rows,
    _create_snapshot,
    _run_real_title_crawl,
    _run_shipped_snapshot_hook,
    _snapshot_hook_name,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_blocked_title_read_does_not_block_another_hooks_result(recursive_test_site, cached_abxpkg_lib_dir):
    title_snapshot = _run_real_title_crawl(recursive_test_site["root_url"], cached_abxpkg_lib_dir)
    title_dir = Path(title_snapshot.output_dir)
    title_file = title_dir / "title/title.txt"
    title = title_file.read_bytes()
    assert title == b"Root"
    records = [json.loads(line) for line in (title_dir / "index.jsonl").read_text().splitlines() if line.strip()]
    record = next(record for record in records if record.get("type") == "ArchiveResult" and record.get("plugin") == "title")
    assert record["status"] == "succeeded"
    event = ArchiveResultEvent.model_validate(record)

    snapshot = _create_snapshot()
    source = Path(snapshot.output_dir) / "source.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("Independent actual capture output.\n" * 100)
    title_file.unlink()
    os.mkfifo(title_file)

    async def run():
        bus = create_bus(name="test_result_storage_isolation")
        ArchiveResultService(bus)
        writer = None
        replay = asyncio.create_task(bus.emit(event).now())
        independent = None
        try:
            # Replay the real hook's durable record through its normal projector.
            # A real FIFO read cannot finish until EOF; keeping the writer open
            # models blocked storage without replacing a handler or filesystem API.
            writer = await asyncio.wait_for(asyncio.to_thread(os.open, title_file, os.O_WRONLY), timeout=5)
            os.write(writer, title)
            independent = asyncio.create_task(
                asyncio.to_thread(
                    _run_shipped_snapshot_hook,
                    snapshot,
                    plugin="hashes",
                    hook_name=_snapshot_hook_name("hashes"),
                    lib_dir=cached_abxpkg_lib_dir,
                ),
            )
            done, _pending = await asyncio.wait({independent}, timeout=5)
            assert independent in done, "A blocked title read held another real hook's DB projection"
            process, result = independent.result()
            assert process.exit_code == 0
            assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
            assert not replay.done(), "The title read must still be waiting for the FIFO writer's EOF"
        finally:
            if writer is not None:
                os.close(writer)
            await replay
            if independent is not None:
                await independent
            await bus.destroy(clear=False)

    try:
        asyncio.run(run())
        title_snapshot.refresh_from_db()
        assert title_snapshot.title == title.decode()
        hashes = json.loads((Path(snapshot.output_dir) / "hashes/hashes.json").read_text())
        assert any(
            item["path"] == "source.txt" and item["hash"] == hashlib.sha256(source.read_bytes()).hexdigest() for item in hashes["files"]
        )
    finally:
        title_file.unlink(missing_ok=True)
        title_file.write_bytes(title)
        _cleanup_machine_process_rows()


def test_depth_zero_result_does_not_probe_url_discovery(cached_abxpkg_lib_dir):
    import sys
    import threading

    snapshot = _create_snapshot()
    assert snapshot.depth == snapshot.crawl.max_depth == 0
    source = Path(snapshot.output_dir) / "source.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("Actual capture at its configured crawl depth.\n")
    urls_file = str(source.parent / "hashes/urls.jsonl")
    probes = []
    exists_code = Path.exists.__code__
    prior_thread_profile, prior_profile = threading.getprofile(), sys.getprofile()

    def observe_path_calls(frame, event, _arg):
        # CPython's audit events omit stat(). Observe the actual Path.exists
        # call without replacing it; include existing Django executor threads.
        if event == "call" and frame.f_code is exists_code and str(frame.f_locals["self"]) == urls_file:
            probes.append(urls_file)

    try:
        threading.setprofile_all_threads(observe_path_calls)
        process, result = _run_shipped_snapshot_hook(
            snapshot,
            plugin="hashes",
            hook_name=_snapshot_hook_name("hashes"),
            lib_dir=cached_abxpkg_lib_dir,
        )
    finally:
        threading.setprofile_all_threads(prior_thread_profile)
        sys.setprofile(prior_profile)
        _cleanup_machine_process_rows()
    assert process.exit_code == 0
    assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert not probes, "A depth-zero hook unnecessarily probed remote archive storage for discovered URLs"
    hashes = json.loads((source.parent / "hashes/hashes.json").read_text())
    assert any(item["path"] == "source.txt" and item["hash"] == hashlib.sha256(source.read_bytes()).hexdigest() for item in hashes["files"])
