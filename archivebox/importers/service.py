"""Generic importer execution: commands discover; ordinary crawls capture."""

import json
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

from abx_dl.execution import iter_plugin_command
from abx_dl.models import PluginEnv
from abx_plugins.plugins.base.importers import read_records
from django.db import IntegrityError, transaction
from django.db.models import Case, F, Value, When
from django.utils import timezone

from archivebox.config.common import build_crawl_config_snapshot, get_config
from archivebox.config.constants import CONSTANTS
from archivebox.crawls.models import Crawl
from archivebox.crawls.schedule_util import next_run_for_schedule
from archivebox.machine.models import Process
from archivebox.misc.util import validate_url
from archivebox.plugins.discovery import get_opencode_provider_keys, get_plugin_catalog

from .catalog import get_importer
from .models import ImporterRun, ImporterSource

logger = logging.getLogger(__name__)
ACTIVE_STATUSES = (ImporterRun.Status.QUEUED, ImporterRun.Status.RUNNING)
WORKER_INTERRUPTED_MESSAGE = "The importer worker stopped. Progress was not advanced; run it again to resume."


def enqueue(source: ImporterSource, action: str) -> ImporterRun:
    # Older API and CLI clients use check for the same discovery operation.
    if action == ImporterRun.Action.CHECK:
        action = ImporterRun.Action.PREVIEW
    if action not in ImporterRun.Action.values:
        raise ValueError("Unknown importer action.")
    definition = get_importer(source.plugin, source.feed)
    try:
        with transaction.atomic():
            # Serialize source edits/reset with enqueue before reading its current
            # checkpoint. This is a short DB-only write, including on SQLite.
            ImporterSource.objects.filter(pk=source.pk).update(name=F("name"))
            source.refresh_from_db()
            if action != ImporterRun.Action.RESET_CODE and definition.auth == "persona" and not source.persona_id:
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
            if source.account.get("id") and (source.checkpoint or definition.auth == "persona"):
                request["expected_account"] = source.account
            if action == ImporterRun.Action.IMPORT and not source.checkpoint:
                preview = (
                    source.runs.filter(action=ImporterRun.Action.PREVIEW, status=ImporterRun.Status.SUCCEEDED)
                    .order_by("-created_at")
                    .values("request", "result", "items")
                    .first()
                )
                if (
                    preview
                    and preview["request"].get("feed") == source.feed
                    and preview["request"].get("settings") == source.settings
                    and preview["result"].get("account", {}).get("id") == source.account.get("id")
                ):
                    request["preview_count"] = len(preview["items"])
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


def _importer_env(source, config):
    payload = config.model_dump(mode="json")
    if source.persona is not None:
        payload.update(source.persona.get_derived_config())
        payload.update(
            AUTH_STORAGE_FILE=source.persona.AUTH_STORAGE_FILE,
            COOKIES_FILE=source.persona.COOKIES_FILE,
        )
    if source.plugin != "importers_browser":
        # Only browser importers learn scripts with OpenCode. Preserve the
        # existing config channel without passing its credentials to other tools.
        # Scope OpenAI even before the dedicated capture schema is installed.
        # Once available, it also enumerates the other keys in this key pane.
        for key in get_opencode_provider_keys() | {"OPENAI_API_KEY"}:
            payload.pop(key, None)
    return PluginEnv(**payload).to_env()


def _read_output(run, command, config, output_dir: Path, cancellation):
    env = _importer_env(run.source, config)
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

    # Resolve config before entering the short DB-only commit. No plugin/network/filesystem work in it.
    crawl = None
    if status == "succeeded" and run.action == ImporterRun.Action.IMPORT and items:
        urls = []
        for item in items:
            url = validate_url(item["url"])
            tags = item.get("metadata", {}).get("tags", [])
            if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                raise ValueError("Importer item tags must be a list of tag names.")
            tags = [tag[:100] for tag in Crawl.parse_tag_names(tags)]
            record = {"url": url, "tags": tags, "title": item.get("title", "")}
            bookmarked_at = item.get("metadata", {}).get("bookmarked_at")
            if bookmarked_at:
                record["bookmarked_at"] = bookmarked_at
            urls.append(json.dumps(record))
        from archivebox.core.models import Folder

        folder_id = Folder.destination(source.folder_id)
        capture_config = build_crawl_config_snapshot(persona=source.persona, overrides={"ONLY_NEW": True, "PARSER": "jsonl"})
        crawl = Crawl(
            # Structured import records retain field boundaries and source metadata.
            urls="\n".join(urls),
            config=capture_config,
            persona=source.persona,
            folder_id=folder_id,
            created_by=source.created_by,
            label=source.name[:64],
            tags_str=source.tags,
            max_depth=0,
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        crawl.set_delete_at_from_config()

    with transaction.atomic():
        # The crawl and completion commit together; a lost CAS rolls both back.
        if crawl is not None:
            Crawl.objects.bulk_create([crawl])
            from archivebox.api.webhook_events import emit_event

            emit_event(crawl, "CREATE")
        if not ImporterRun.objects.filter(pk=run.pk, status=ImporterRun.Status.RUNNING, cancel_requested=False).update(
            status=status,
            crawl=crawl,
            items=items,
            result=result,
            message=str(result.get("message", ""))[:4000],
            finished_at=timezone.now(),
        ):
            raise InterruptedError("Importer cancelled. Progress was not advanced.")
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


def run_next_importer(stop_event=None, *, run_id=None) -> bool:
    """Claim one queued run, optionally the exact run selected by a CLI caller."""
    queued = ImporterRun.objects.filter(status=ImporterRun.Status.QUEUED)
    if run_id is not None:
        queued = queued.filter(pk=run_id)
    run = queued.select_related("source__persona", "source__created_by").order_by("created_at").first()
    if run is None:
        return False
    if not ImporterRun.objects.filter(pk=run.pk, status=ImporterRun.Status.QUEUED).update(
        status=ImporterRun.Status.RUNNING,
        owner=Process.current(),
        started_at=timezone.now(),
    ):
        return False
    try:
        if run.action == ImporterRun.Action.RESET_CODE:
            # The active-run constraint excludes discovery while its state is
            # removed. Filesystem work happens outside any DB transaction.
            state = CONSTANTS.DATA_DIR / "importers" / str(run.source_id) / "state"
            if state.is_symlink():
                raise ValueError("The learned code directory is a symlink; reset it on the server directly.")
            if state.exists():
                for path in state.iterdir():
                    if path.name == ".git":
                        continue
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            ImporterRun.objects.filter(pk=run.pk).update(
                status=ImporterRun.Status.SUCCEEDED,
                message="Learned code reset. The next browser run will learn again. Progress, captures and run history are unchanged.",
                finished_at=timezone.now(),
            )
            return True
        get_importer(run.source.plugin, run.source.feed)
        catalog = get_plugin_catalog()
        command = catalog.command(run.source.plugin, "import")
        output_dir = CONSTANTS.DATA_DIR / "importers" / str(run.source_id) / str(run.pk)
        output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        config = get_config(persona=run.source.persona)
        cancellation = Cancellation(run.pk, stop_event)
        items, result = _read_output(run, command, config, output_dir, cancellation)
        _finish(run, items, result)
    except (Exception, KeyboardInterrupt) as error:  # - isolate optional plugin failures from capture dispatch
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            (output_dir / "command-error.log").write_text(str(error.stderr))
        # Command arguments never contain cookies or source settings; those use env/stdin.
        message: str | Case = (
            str(error)[:2000]
            if isinstance(error, (ValueError, InterruptedError))
            else f"{type(error).__name__}: importer command failed; progress was not advanced."
        )
        logger.warning("Importer run %s failed (%s)", run.pk, type(error).__name__)
        status: str | Case = ImporterRun.Status.FAILED
        if isinstance(error, (InterruptedError, KeyboardInterrupt)):
            # The command sees both Pause and worker shutdown as interruption.
            # Classify against the durable Pause flag in the same write.
            status = Case(When(cancel_requested=True, then=Value(ImporterRun.Status.CANCELLED)), default=Value(status))
            message = Case(When(cancel_requested=True, then=Value(message)), default=Value(WORKER_INTERRUPTED_MESSAGE))
        ImporterRun.objects.filter(pk=run.pk, status=ImporterRun.Status.RUNNING).update(
            status=status,
            message=message,
            finished_at=timezone.now(),
        )
    return True


def recover_interrupted() -> None:
    # Recovery only checks the owner PID. Imported items, saved requests and
    # process logs can be large and must not be decoded on every idle poll.
    runs = (
        ImporterRun.objects.filter(status=ImporterRun.Status.RUNNING)
        .select_related("owner")
        .only(
            "id",
            "owner__machine_id",
            "owner__env",
            "owner__pid",
            "owner__started_at",
            "owner__cmd",
            "owner__status",
        )
    )
    for run in runs:
        if run.owner is None or not run.owner.is_running:
            ImporterRun.objects.filter(pk=run.pk, status=ImporterRun.Status.RUNNING).update(
                status=Case(
                    When(cancel_requested=True, then=Value(ImporterRun.Status.CANCELLED)),
                    default=Value(ImporterRun.Status.FAILED),
                ),
                message=Case(
                    When(cancel_requested=True, then=Value("Importer cancelled. Progress was not advanced.")),
                    default=Value(WORKER_INTERRUPTED_MESSAGE),
                ),
                finished_at=timezone.now(),
            )


_thread = None
_stop = threading.Event()


def _background_run():
    from django.db import connections
    from archivebox.config.common import get_config, normalize_runtime_config
    from archivebox.plugins.discovery import current_process_attributes, plugin_operation

    config = normalize_runtime_config(get_config())
    attributes = current_process_attributes()
    try:
        while not _stop.is_set():
            # This independent thread outlives any scheduler pass that started
            # it. Give each active iteration its own completed worker operation.
            with plugin_operation("archivebox.importers.service._background_run", config, attributes=attributes):
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


def save_source(source, values):
    """Validate native source edits with the UI's plugin-derived form and CAS guard."""
    from django.core.exceptions import ValidationError
    from .forms import ImporterSourceForm

    creating = source._state.adding
    definition = get_importer(values.get("plugin", source.plugin), values.get("feed", source.feed))
    if not creating and (definition.plugin, definition.feed) != (source.plugin, source.feed):
        raise ValueError("Create a new source to change the importer plugin or feed.")
    settings = values.get("settings", source.settings)
    if not isinstance(settings, dict):
        raise ValueError("Settings must be a JSON object.")
    if any(value is None and key not in {"persona_id", "folder_id"} for key, value in values.items()):
        raise ValueError("Only persona_id and folder_id can be cleared with null.")
    unknown = set(settings) - set(definition.fields)
    if unknown:
        raise ValueError(f"Unknown importer settings: {', '.join(sorted(unknown))}")
    data = {key: values.get(key, getattr(source, key)) for key in ImporterSourceForm._meta.fields if key not in {"persona", "folder"}}
    data["persona"] = values.get("persona_id", source.persona_id)
    data["folder"] = values.get("folder_id", source.folder_id)
    data.update({f"setting_{key}": settings.get(key, spec.get("default", "")) for key, spec in definition.fields.items()})
    form = ImporterSourceForm(data, instance=source, definition=definition)
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    return form.save(enabled=values.get("enabled"))


def source_action(source, action):
    """The same queued actions are available to the UI, REST API and CLI."""
    if action in ImporterRun.Action.values:
        return enqueue(source, action)
    if action == "pause":
        pause(source)
    elif action == "resume":
        source.enabled = True
        source.next_run_at = next_run_for_schedule(source.schedule, timezone.now()) if source.schedule else None
        source.save(update_fields=["enabled", "next_run_at"])
    elif action == "reset":
        if not ImporterSource.objects.filter(pk=source.pk).exclude(runs__status__in=ACTIVE_STATUSES).update(checkpoint={}, account={}):
            raise ValueError("Pause the importer and wait for its active run before resetting progress.")
    else:
        raise ValueError("Unknown importer action.")
    source.refresh_from_db()
    return source


def delete_source(source):
    # Serialize deletion with enqueue's source write. No browser or filesystem I/O.
    with transaction.atomic():
        ImporterSource.objects.filter(pk=source.pk).update(name=F("name"))
        if source.runs.filter(status__in=ACTIVE_STATUSES).exists():
            raise ValueError("Pause the importer and wait for its active run before deleting it.")
        source.delete()
