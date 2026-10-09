"""Generic importer execution: commands discover; ordinary crawls capture."""

import json
import logging
import subprocess
import threading
import time
from pathlib import Path

from abx_dl.execution import iter_plugin_command
from abx_dl.models import PluginEnv
from abx_plugins.plugins.base.importers import read_records
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from archivebox.config.common import build_crawl_config_snapshot, get_config
from archivebox.config.constants import CONSTANTS
from archivebox.crawls.models import Crawl
from archivebox.crawls.schedule_util import next_run_for_schedule
from archivebox.machine.models import Process
from archivebox.plugins.discovery import get_plugin_catalog

from .catalog import get_importer
from .models import ImporterRun, ImporterSource

logger = logging.getLogger(__name__)
ACTIVE_STATUSES = (ImporterRun.Status.QUEUED, ImporterRun.Status.RUNNING)


def enqueue(source: ImporterSource, action: str) -> ImporterRun:
    if action not in ImporterRun.Action.values:
        raise ValueError("Unknown importer action.")
    definition = get_importer(source.plugin, source.feed)
    try:
        with transaction.atomic():
            # Serialize source edits/reset with enqueue before reading its current
            # checkpoint. This is a short DB-only write, including on SQLite.
            ImporterSource.objects.filter(pk=source.pk).update(name=F("name"))
            source.refresh_from_db()
            if definition.auth == "persona" and not source.persona_id:
                raise ValueError("Select a persona before running this importer.")
            request = {
                "version": 1,
                "action": action,
                "feed": source.feed,
                "settings": source.settings,
                "checkpoint": source.checkpoint if action == ImporterRun.Action.IMPORT else {},
                "limit": min(source.limit, 20) if action == ImporterRun.Action.PREVIEW else source.limit,
                "all": action == ImporterRun.Action.IMPORT,
            }
            return ImporterRun.objects.create(source=source, action=action, request=request)
    except IntegrityError:
        active = source.runs.filter(status__in=ACTIVE_STATUSES).first()
        if active is None:
            raise
        return active


def pause(source: ImporterSource) -> None:
    with transaction.atomic():
        ImporterSource.objects.filter(pk=source.pk).update(enabled=False, next_run_at=None)
        source.runs.filter(status=ImporterRun.Status.QUEUED).update(
            status=ImporterRun.Status.CANCELLED,
            finished_at=timezone.now(),
            message="Cancelled before starting.",
        )
        source.runs.filter(status=ImporterRun.Status.RUNNING).update(cancel_requested=True)


def enqueue_due() -> None:
    now = timezone.now()
    for source in ImporterSource.objects.filter(enabled=True, next_run_at__lte=now).exclude(schedule=""):
        next_run = next_run_for_schedule(source.schedule, now)
        # One short transaction couples advancing the schedule with durable enqueue.
        try:
            with transaction.atomic():
                if ImporterSource.objects.filter(pk=source.pk, enabled=True, next_run_at=source.next_run_at).update(next_run_at=next_run):
                    enqueue(source, ImporterRun.Action.IMPORT)
        except ValueError as error:
            # A removed plugin should be visible on its source, not break capture scheduling.
            ImporterSource.objects.filter(pk=source.pk).update(enabled=False, next_run_at=None)
            ImporterRun.objects.create(source=source, status=ImporterRun.Status.FAILED, message=str(error), finished_at=now)


class Cancellation:
    """The command runner polls this just like a threading.Event."""

    def __init__(self, run_id, stop_event=None):
        self.run_id = run_id
        self.stop_event = stop_event
        self.last_check = 0.0
        self.cancelled = False

    def is_set(self):
        from archivebox.core.shutdown_util import raise_if_shutdown_requested

        if self.stop_event and self.stop_event.is_set():
            self.cancelled = True
        try:
            raise_if_shutdown_requested()
        except KeyboardInterrupt:
            self.cancelled = True
        if not self.cancelled and time.monotonic() - self.last_check >= 0.25:
            self.cancelled = not ImporterRun.objects.filter(
                pk=self.run_id,
                status=ImporterRun.Status.RUNNING,
                cancel_requested=False,
            ).exists()
            self.last_check = time.monotonic()
        return self.cancelled


def _read_output(run, command, config, output_dir: Path, cancellation):
    payload = config.model_dump(mode="json")
    if run.source.persona is not None:
        payload.update(run.source.persona.get_derived_config())
    env = PluginEnv(**payload).to_env()
    env["DATA_DIR"] = str(CONSTANTS.DATA_DIR)
    env["IMPORTERS_STATE_DIR"] = str(output_dir.parent / "state")
    timeout = get_importer(run.source.plugin, run.source.feed).timeout
    env["IMPORTERS_TIMEOUT"] = str(timeout)

    def progress(message):
        ImporterRun.objects.filter(pk=run.pk, status=ImporterRun.Status.RUNNING).update(message=message)

    output = iter_plugin_command(
        command,
        stdin=[json.dumps(run.request)],
        env=env,
        cwd=output_dir,
        timeout=timeout,
        stop_event=cancellation,
        termination_grace=15,
    )
    try:
        records = list(read_records(output, run.request, on_progress=progress))
    except ValueError:
        if cancellation.is_set():
            raise InterruptedError("Importer cancelled. Progress was not advanced.") from None
        raise
    finally:
        output.close()
    if cancellation.is_set():
        raise InterruptedError("Importer cancelled. Progress was not advanced.")
    return records[:-1], records[-1]


def _finish(run, items, result):
    source = run.source
    account = result.get("account", {})
    status = result["status"]
    definition = get_importer(source.plugin, source.feed)
    if status == "succeeded":
        if definition.auth == "persona" and not account.get("id"):
            raise ValueError("The importer did not identify the authenticated account.")
        identity_pinned = source.checkpoint or (definition.auth == "persona" and source.account.get("id"))
        if identity_pinned and source.account.get("id") != account.get("id"):
            raise ValueError("The connected account changed. Reset progress before importing from the new account.")
        if run.action == ImporterRun.Action.IMPORT and result.get("has_more") and result.get("checkpoint", {}) == source.checkpoint:
            raise ValueError("The importer reported more items without advancing its checkpoint. Progress was not advanced.")

    # Resolve config before entering the short DB-only commit. No plugin/network/filesystem work in it.
    crawl = None
    if status == "succeeded" and run.action == ImporterRun.Action.IMPORT and items:
        capture_config = build_crawl_config_snapshot(persona=source.persona, overrides={"ONLY_NEW": True})
        crawl = Crawl(
            # Discovery already validated these URLs. Keep provenance/titles on
            # the run; ordinary URL submission must not depend on input parsers.
            urls="\n".join(item["url"] for item in items),
            config=capture_config,
            persona=source.persona,
            created_by=source.created_by,
            label=source.name[:64],
            tags_str=source.tags,
            max_depth=0,
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        crawl.set_delete_at_from_config()

    with transaction.atomic():
        # Acquire the write through a CAS before creating a crawl or advancing its source.
        if not ImporterRun.objects.filter(pk=run.pk, status=ImporterRun.Status.RUNNING, cancel_requested=False).update(
            status=status,
            items=items,
            result=result,
            message=str(result.get("message", ""))[:4000],
            finished_at=timezone.now(),
        ):
            raise InterruptedError("Importer cancelled. Progress was not advanced.")
        if crawl is not None:
            Crawl.objects.bulk_create([crawl])
            ImporterRun.objects.filter(pk=run.pk).update(crawl=crawl)
        if status == "succeeded":
            updates = {"account": account}
            if run.action == ImporterRun.Action.IMPORT:
                updates["checkpoint"] = result.get("checkpoint", {})
            ImporterSource.objects.filter(pk=source.pk).update(**updates)
            if run.action == ImporterRun.Action.IMPORT and run.request.get("all") and result.get("has_more"):
                ImporterRun.objects.create(
                    source=source,
                    action=ImporterRun.Action.IMPORT,
                    request={**run.request, "checkpoint": updates["checkpoint"]},
                )
        elif status == "needs_login":
            ImporterSource.objects.filter(pk=source.pk).update(enabled=False, next_run_at=None)


def run_next_importer(stop_event=None) -> bool:
    run = (
        ImporterRun.objects.filter(status=ImporterRun.Status.QUEUED)
        .select_related("source__persona", "source__created_by")
        .order_by("created_at")
        .first()
    )
    if run is None:
        return False
    if not ImporterRun.objects.filter(pk=run.pk, status=ImporterRun.Status.QUEUED).update(
        status=ImporterRun.Status.RUNNING,
        owner=Process.current(),
        started_at=timezone.now(),
    ):
        return False
    try:
        get_importer(run.source.plugin, run.source.feed)
        command = get_plugin_catalog().command(run.source.plugin, "import")
        output_dir = CONSTANTS.DATA_DIR / "importers" / str(run.source_id) / str(run.pk)
        output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        config = get_config(persona=run.source.persona)
        cancellation = Cancellation(run.pk, stop_event)
        items, result = _read_output(run, command, config, output_dir, cancellation)
        _finish(run, items, result)
    except (Exception, KeyboardInterrupt) as error:  # - isolate optional plugin failures from capture dispatch
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            (output_dir / "command-error.log").write_text(str(error.stderr))
        cancelled = isinstance(error, (InterruptedError, KeyboardInterrupt))
        # Command arguments never contain cookies or source settings; those use env/stdin.
        message = (
            str(error)[:2000]
            if isinstance(error, (ValueError, InterruptedError))
            else f"{type(error).__name__}: importer command failed; progress was not advanced."
        )
        logger.warning("Importer run %s failed (%s)", run.pk, type(error).__name__)
        ImporterRun.objects.filter(pk=run.pk, status=ImporterRun.Status.RUNNING).update(
            status=ImporterRun.Status.CANCELLED if cancelled else ImporterRun.Status.FAILED,
            message=message,
            finished_at=timezone.now(),
        )
    return True


def recover_interrupted() -> None:
    for run in ImporterRun.objects.filter(status=ImporterRun.Status.RUNNING).select_related("owner"):
        if run.owner is None or not run.owner.is_running:
            ImporterRun.objects.filter(pk=run.pk, status=ImporterRun.Status.RUNNING).update(
                status=ImporterRun.Status.FAILED,
                message="The importer worker stopped. Progress was not advanced; run it again to resume.",
                finished_at=timezone.now(),
            )


_thread = None
_stop = threading.Event()


def _background_run():
    from django.db import connections

    try:
        while not _stop.is_set():
            recover_interrupted()
            enqueue_due()
            worked = run_next_importer(_stop)
            connections.close_all()
            if not worked:
                _stop.wait(2)
    finally:
        connections.close_all()


def shutdown():
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)


def tick(*, daemon: bool) -> bool:
    """Keep discovery independent of the capture runner's blocking crawl dispatch."""
    global _thread
    if not daemon:
        recover_interrupted()
        return run_next_importer()
    if _thread is None or not _thread.is_alive():
        if _thread is None:
            import atexit

            atexit.register(shutdown)
        _stop.clear()
        _thread = threading.Thread(target=_background_run, name="archivebox-importers", daemon=True)
        _thread.start()
    return False
