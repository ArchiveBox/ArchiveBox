"""Private rclone configuration and durable, non-destructive archive copies."""

import atexit
import configparser
import os
import platform
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from abxpkg.exceptions import ABXPkgError
from django.db import IntegrityError, connections
from django.utils import timezone

from archivebox.config.constants import CONSTANTS
from archivebox.core.models import Snapshot
from archivebox.machine.models import Process
from archivebox.uuid_compat import uuid7
from archivebox.workers.supervisord_util import resolve_env_binary

from .models import StorageDestination, StorageRun

ACTIVE = (StorageRun.Status.QUEUED, StorageRun.Status.RUNNING)


def private_dir(destination):
    path = CONSTANTS.DATA_DIR / "storage" / str(destination.pk)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def config_path(destination, *, revision=None):
    revision = destination.config_revision if revision is None else revision
    return private_dir(destination) / (f"rclone.{revision}.conf" if revision else "rclone.conf")


def read_options(destination):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_path(destination))
    return dict(parser["archivebox"]) if parser.has_section("archivebox") else {}


def write_options(destination, options):
    parser = configparser.ConfigParser(interpolation=None)
    parser["archivebox"] = options
    with tempfile.NamedTemporaryFile(mode="w", dir=private_dir(destination), delete=False) as output:
        parser.write(output)
        temporary = Path(output.name)
    try:
        temporary.chmod(0o600)
        revision = uuid7().hex
        os.replace(temporary, config_path(destination, revision=revision))
        destination.config_revision = revision
    finally:
        temporary.unlink(missing_ok=True)


def enqueue(destination, action):
    if action not in StorageRun.Action.values:
        raise ValueError("Unknown storage action.")
    # Read path and credential revision together. Edits publish a new immutable
    # file before changing this DB pointer, so a concurrent enqueue keeps one
    # complete configuration even if the edit passed its active-job check first.
    destination = StorageDestination.objects.get(pk=destination.pk)
    try:
        return StorageRun.objects.create(
            destination=destination,
            destination_path=destination.path,
            config_revision=destination.config_revision,
            action=action,
        )
    except IntegrityError:
        active = destination.runs.filter(status__in=ACTIVE).first()
        if active is None:
            raise
        return active


def _run_rclone(run, arguments, *, timeout=600, stop_event=None):
    """Keep credentials in the private config, never argv, DB command logs or HTML."""
    binary = resolve_env_binary("rclone")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("RCLONE_")}
    command = [
        str(binary),
        "--config",
        str(config_path(run.destination, revision=run.config_revision)),
        "--retries",
        "1",
        "--low-level-retries",
        "1",
        "--contimeout",
        "20s",
        "--timeout",
        "60s",
        *arguments,
    ]
    log_path = private_dir(run.destination) / f"{run.pk}.log"
    descriptor = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "ab") as log:
        process = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        started = time.monotonic()
        try:
            while process.poll() is None:
                cancelled = stop_event is not None and stop_event.is_set()
                cancelled = cancelled or StorageRun.objects.filter(pk=run.pk, cancel_requested=True).exists()
                if cancelled:
                    raise InterruptedError("Cancelled. Files already copied remain at the destination.")
                if time.monotonic() - started > timeout:
                    raise TimeoutError("The storage operation exceeded its time limit. Inspect the private rclone log.")
                time.sleep(0.2)
            if process.returncode:
                raise RuntimeError(
                    f"rclone exited with code {process.returncode}. Check your destination, credentials and access permissions. Details are in the private storage log.",
                )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def run_next(stop_event=None, *, run_id=None):
    queued = StorageRun.objects.filter(status=StorageRun.Status.QUEUED)
    if run_id:
        queued = queued.filter(pk=run_id)
    run = queued.select_related("destination").order_by("created_at").first()
    if run is None:
        return False
    if not StorageRun.objects.filter(pk=run.pk, status=StorageRun.Status.QUEUED).update(
        status=StorageRun.Status.RUNNING,
        started_at=timezone.now(),
        owner=Process.current(),
    ):
        return False
    try:
        destination = run.destination
        remote = f"archivebox:{run.destination_path.rstrip('/')}"
        if run.action == StorageRun.Action.INSTALL:
            from abxpkg import AptProvider, Binary, BrewProvider, EnvProvider

            provider = BrewProvider() if platform.system() == "Darwin" else AptProvider()
            binary = Binary(name="rclone", binproviders=[EnvProvider(), provider]).install()
            if not binary.loaded_abspath:
                raise RuntimeError("rclone installation did not return an executable. Check the server package-manager permissions.")
            message = f"rclone {binary.loaded_version} is installed. Check your storage connection next."
        elif run.action == StorageRun.Action.CHECK:
            # Read, write and read-back prove access without touching existing files.
            with tempfile.TemporaryDirectory(prefix="archivebox-storage-check-") as temporary:
                probe = Path(temporary) / "probe.txt"
                probe.write_text(f"ArchiveBox storage access check {run.pk}\n")
                probe_remote = f"{remote}/.archivebox-check-{run.pk}"
                _run_rclone(run, ["copyto", str(probe), probe_remote], timeout=60, stop_event=stop_event)
                try:
                    restored = Path(temporary) / "restored.txt"
                    _run_rclone(run, ["copyto", probe_remote, str(restored)], timeout=60, stop_event=stop_event)
                    if restored.read_bytes() != probe.read_bytes():
                        raise RuntimeError("The storage access check returned different bytes.")
                finally:
                    _run_rclone(run, ["deletefile", probe_remote], timeout=60)
            StorageDestination.objects.filter(
                pk=destination.pk,
                path=run.destination_path,
                config_revision=run.config_revision,
            ).update(checked_at=timezone.now())
            message = "Connection verified: wrote, read back and removed a temporary test file."
        else:
            snapshots = Snapshot.objects.filter(status=Snapshot.StatusChoices.SEALED, modified_at__lte=run.created_at).order_by("id")
            total = snapshots.count()
            StorageRun.objects.filter(pk=run.pk).update(total_snapshots=total)
            for snapshot in snapshots.iterator(chunk_size=100):
                source = Path(snapshot.output_dir)
                if not source.is_dir():
                    raise RuntimeError(f"Snapshot {snapshot.pk} has no saved directory; no success was recorded for it.")
                relative = source.relative_to(CONSTANTS.ARCHIVE_DIR)
                target = f"{remote}/archive/{relative.as_posix()}"
                _run_rclone(run, ["copy", str(source), target, "--checksum"], stop_event=stop_event)
                _run_rclone(run, ["check", str(source), target, "--one-way", "--download"], stop_event=stop_event)
                run.copied_snapshots += 1
                StorageRun.objects.filter(pk=run.pk).update(copied_snapshots=run.copied_snapshots)
            message = f"Copied and verified {run.copied_snapshots} sealed snapshots. The local archive is unchanged."
        StorageRun.objects.filter(pk=run.pk).update(status=StorageRun.Status.SUCCEEDED, finished_at=timezone.now(), message=message)
    except InterruptedError as error:
        StorageRun.objects.filter(pk=run.pk).update(status=StorageRun.Status.CANCELLED, finished_at=timezone.now(), message=str(error))
    except (OSError, RuntimeError, ValueError, ABXPkgError) as error:
        # Never expose subprocess output or credential-bearing provider errors.
        message = (
            str(error)
            if isinstance(error, (RuntimeError, TimeoutError))
            else "Storage operation failed. Inspect the private storage log and destination configuration."
        )
        StorageRun.objects.filter(pk=run.pk).update(status=StorageRun.Status.FAILED, finished_at=timezone.now(), message=message)
    return True


def recover_interrupted():
    for run in StorageRun.objects.filter(status=StorageRun.Status.RUNNING).select_related("owner"):
        if run.owner is None or not run.owner.is_running:
            StorageRun.objects.filter(pk=run.pk, status=StorageRun.Status.RUNNING).update(
                status=StorageRun.Status.FAILED,
                finished_at=timezone.now(),
                message="The storage worker stopped. Start a new copy to verify and continue existing files.",
            )


_thread = None
_stop = threading.Event()


def _background():
    try:
        while not _stop.is_set():
            recover_interrupted()
            worked = run_next(_stop)
            connections.close_all()
            if not worked:
                _stop.wait(2)
    finally:
        connections.close_all()


def shutdown():
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)


def tick(*, daemon):
    global _thread
    if not daemon:
        recover_interrupted()
        return run_next()
    if _thread is None or not _thread.is_alive():
        if _thread is None:
            atexit.register(shutdown)
        _stop.clear()
        _thread = threading.Thread(target=_background, name="archivebox-storage", daemon=True)
        _thread.start()
    return False
