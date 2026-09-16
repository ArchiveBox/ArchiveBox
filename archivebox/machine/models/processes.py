from __future__ import annotations

import os
import signal
import socket
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.db import models
from django.db.models import Q, QuerySet
from django.utils import timezone

from archivebox.base_models.models import ModelWithDeleteAfter
from archivebox.config import CONSTANTS
from archivebox.config.common import rprint
from archivebox.machine import models as state
from archivebox.uuid_compat import CompactUUIDField, uuid7

from .binaries import Binary
from .constants import (
    PID_REUSE_WINDOW,
    PROCESS_PID_NAMESPACE_KEY,
    PROCESS_RECHECK_INTERVAL,
    PROCESS_TIMEOUT_GRACE,
    PSUTIL_AVAILABLE,
    START_TIME_TOLERANCE,
    psutil,
)
from .interfaces import NetworkInterface
from .machines import Machine

if TYPE_CHECKING:
    from archivebox.core.models import ArchiveResult


def get_current_pid_namespace() -> str:
    """Return the OS PID namespace that makes numeric PIDs meaningful."""
    try:
        return os.readlink("/proc/self/ns/pid")
    except OSError:
        return f"host:{socket.gethostname()}"


def _default_exit_code_for_unowned_process(process_type: str) -> int:
    # Hooks are externally visible work items. If their owning runner disappeared
    # before recording the real exit code, retrying is safer than converting an
    # unknown interrupted extraction into a durable success/no-result row.
    return 128 + signal.SIGTERM if process_type == Process.TypeChoices.HOOK else 0


def _get_process_binary_env_keys(plugin_name: str, hook_path: str, env: dict[str, Any] | None) -> list[str]:
    env = env or {}
    plugin_name = str(plugin_name or "").strip()
    hook_path = str(hook_path or "").strip()
    plugin_key = plugin_name.upper().replace("-", "_")
    keys: list[str] = []
    seen: set[str] = set()

    def add(key: str) -> None:
        if key and key not in seen and env.get(key):
            seen.add(key)
            keys.append(key)

    if plugin_key:
        add(f"{plugin_key}_BINARY")

    try:
        from archivebox.plugins.discovery import discover_plugin_configs

        plugin_schema = discover_plugin_configs().get(plugin_name, {})
        schema_keys = [key for key in (plugin_schema.get("properties") or {}) if key.endswith("_BINARY")]
    except Exception:
        schema_keys = []

    schema_keys.sort(
        key=lambda key: (
            key != f"{plugin_key}_BINARY",
            key,
        ),
    )
    for key in schema_keys:
        add(key)

    if plugin_name.startswith("search_backend_"):
        backend_name = plugin_name.removeprefix("search_backend_").upper().replace("-", "_")
        configured_engine = str(env.get("SEARCH_BACKEND_ENGINE") or "").strip().upper().replace("-", "_")
        if backend_name and backend_name == configured_engine:
            add(f"{backend_name}_BINARY")

    hook_suffix = Path(hook_path).suffix.lower()
    if hook_suffix == ".js":
        add("NODE_BINARY")

    return keys


class ProcessManager(models.Manager):
    """Manager for Process model."""

    def current(self) -> Process:
        """Get the Process record for the current OS process."""
        return Process.current()


class Process(ModelWithDeleteAfter, models.Model):
    """
    Tracks a single OS process execution.

    Process represents the actual subprocess spawned to execute a hook.
    One Process can optionally be associated with an ArchiveResult (via OneToOne),
    but Process can also exist standalone for internal operations.

    Follows the unified process lifecycle:
    - queued: Process ready to launch
    - running: Process actively executing
    - exited: Process completed (check exit_code for success/failure)

    Direct Process methods and the abx-dl event projector own these transitions.
    Keeping the DB row as the only lifecycle state makes interrupted subprocess
    recovery observable without reconciling a second in-memory state machine.
    """

    class StatusChoices(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        EXITED = "exited", "Exited"

    class TypeChoices(models.TextChoices):
        SUPERVISORD = "supervisord", "Supervisord"
        ORCHESTRATOR = "orchestrator", "Orchestrator"
        SERVER = "server", "Server"
        UPDATE = "update", "Update"
        ADD = "add", "Add"
        SEARCH = "search", "Search"
        WORKER = "worker", "Worker"
        CLI = "cli", "CLI"
        HOOK = "hook", "Hook"
        BINARY = "binary", "Binary"

    # Primary fields
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    # Machine FK - required (every process runs on a machine)
    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        null=False,
        related_name="process_set",
        help_text="Machine where this process executed",
    )

    # Parent process (optional)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        help_text="Parent process that spawned this process",
    )

    # Process type (cli, worker, orchestrator, binary, supervisord)
    process_type = models.CharField(
        max_length=16,
        choices=TypeChoices.choices,
        default=TypeChoices.CLI,
        db_index=True,
        help_text="Type of process (cli, worker, orchestrator, binary, supervisord)",
    )

    # Worker type (only for WORKER processes: crawl, snapshot, archiveresult)
    worker_type = models.CharField(
        max_length=32,
        default="",
        null=False,
        blank=True,
        db_index=True,
        help_text="Worker role name for worker/orchestrator subprocesses",
    )

    # Execution metadata
    pwd = models.CharField(
        max_length=512,
        default="",
        null=False,
        blank=True,
        help_text="Working directory for process execution",
    )
    cmd = models.JSONField(
        default=list,
        null=False,
        blank=True,
        help_text="Command as array of arguments",
    )
    env = models.JSONField(
        default=dict,
        null=False,
        blank=True,
        help_text="Environment variables for process",
    )
    timeout = models.IntegerField(
        default=120,
        null=False,
        help_text="Timeout in seconds",
    )

    # Process results
    pid = models.IntegerField(
        default=None,
        null=True,
        blank=True,
        help_text="OS process ID",
    )
    exit_code = models.IntegerField(
        default=None,
        null=True,
        blank=True,
        help_text="Process exit code (0 = success)",
    )
    stdout = models.TextField(
        default="",
        null=False,
        blank=True,
        help_text="Standard output from process",
    )
    stderr = models.TextField(
        default="",
        null=False,
        blank=True,
        help_text="Standard error from process",
    )

    # Timing
    started_at = models.DateTimeField(
        default=None,
        null=True,
        blank=True,
        help_text="When process was launched",
    )
    ended_at = models.DateTimeField(
        default=None,
        null=True,
        blank=True,
        help_text="When process completed/terminated",
    )

    # Optional FKs
    binary = models.ForeignKey(
        Binary,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="process_set",
        help_text="Binary used by this process",
    )
    iface = models.ForeignKey(
        NetworkInterface,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="process_set",
        help_text="Network interface used by this process",
    )

    # Optional connection URL (for CDP, sonic, etc.)
    url = models.URLField(
        max_length=2048,
        default=None,
        null=True,
        blank=True,
        help_text="Connection URL (CDP endpoint, sonic server, etc.)",
    )

    # Reverse relation to ArchiveResult (OneToOne from AR side)
    # archiveresult: OneToOneField defined on ArchiveResult model

    # Durable process lifecycle fields
    status = models.CharField(
        max_length=16,
        choices=StatusChoices.choices,
        default=StatusChoices.QUEUED,
        db_index=True,
    )
    retry_at = models.DateTimeField(
        default=timezone.now,
        null=True,
        blank=True,
        db_index=True,
        help_text="When to retry this process",
    )

    machine_id: uuid.UUID
    parent_id: uuid.UUID | None
    binary_id: uuid.UUID | None
    children: models.Manager[Process]
    archiveresult: ArchiveResult

    delete_after_final_statuses = (StatusChoices.EXITED,)

    objects = ProcessManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    class Meta(ModelWithDeleteAfter.Meta):
        app_label = "machine"
        verbose_name = "Process"
        verbose_name_plural = "Processes"
        indexes = [
            models.Index(fields=["machine", "status", "retry_at"]),
            models.Index(fields=["binary", "exit_code"]),
            models.Index(fields=["pid", "started_at"]),
            models.Index(fields=["process_type", "worker_type", "pwd", "started_at"]),
            models.Index(fields=["machine", "process_type", "-modified_at"], name="mach_proc_recent_idx"),
            models.Index(fields=["machine", "status", "process_type"], name="mach_proc_running_idx"),
        ]
        constraints = [
            # This is deliberately machine-scoped. It prevents two locally
            # verifiable runners from working the same collection, while not
            # claiming to coordinate independent hosts that share a database.
            # Cross-machine work ownership belongs to short Crawl/Snapshot CAS
            # claims so PostgreSQL deployments can support that model later.
            models.UniqueConstraint(
                fields=["machine", "pwd"],
                condition=Q(status="running", process_type="orchestrator", worker_type="worker_runner"),
                name="single_active_runner_per_data_dir",
            ),
        ]

    def __str__(self) -> str:
        cmd_str = " ".join(self.cmd[:3]) if self.cmd else "(no cmd)"
        return f"Process[{self.id}] {cmd_str} ({self.status})"

    def get_delete_after_config_value(self):
        value = self.env.get("DELETE_AFTER")
        if value not in (None, ""):
            return value
        value = (self.machine.config or {}).get("DELETE_AFTER")
        if value not in (None, ""):
            return value
        return "0"

    @classmethod
    def missing_delete_at_candidates(cls):
        return cls.objects.filter(delete_at__isnull=True).filter(
            Q(env__has_key="DELETE_AFTER") | Q(machine__config__has_key="DELETE_AFTER"),
        )

    # Properties that delegate to related objects
    @property
    def cmd_version(self) -> str:
        """Get version from associated binary."""
        return self.binary.version if self.binary else ""

    @property
    def bin_abspath(self) -> str:
        """Get absolute path from associated binary."""
        return self.binary.abspath if self.binary else ""

    @property
    def plugin(self) -> str:
        """Get plugin name from associated ArchiveResult (if any)."""
        try:
            return self.archiveresult.plugin
        except Process.archiveresult.RelatedObjectDoesNotExist:
            return ""

    @property
    def hook_name(self) -> str:
        """Get hook name from associated ArchiveResult (if any)."""
        try:
            return self.archiveresult.hook_name
        except Process.archiveresult.RelatedObjectDoesNotExist:
            return ""

    def to_json(self) -> dict:
        """
        Convert Process model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION

        record = {
            "type": "Process",
            "schema_version": VERSION,
            "id": str(self.id),
            "machine_id": str(self.machine_id),
            "cmd": self.cmd,
            "pwd": self.pwd,
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }
        # Include optional fields if set
        if self.binary_id:
            record["binary_id"] = str(self.binary_id)
        if self.pid:
            record["pid"] = self.pid
        if self.timeout:
            record["timeout"] = self.timeout
        return record

    def hydrate_binary_from_context(self, *, plugin_name: str = "", hook_path: str = "") -> Binary | None:
        from archivebox.machine.models import Machine, _find_existing_binary_for_reference

        machine = self.machine if self.machine_id else Machine.current()

        references: list[str] = []
        for key in _get_process_binary_env_keys(plugin_name, hook_path, self.env):
            value = str(self.env.get(key) or "").strip()
            if value and value not in references:
                references.append(value)

        if self.cmd:
            cmd_0 = str(self.cmd[0]).strip()
            if cmd_0 and cmd_0 not in references:
                references.append(cmd_0)

        for reference in references:
            binary = _find_existing_binary_for_reference(machine, reference)
            if binary:
                self.binary = binary
                return binary

        return None

    @classmethod
    def parse_records_from_text(cls, text: str) -> list[dict]:
        """Parse JSONL records from raw text using the shared JSONL parser."""
        from archivebox.misc.jsonl import parse_line

        records: list[dict] = []
        if not text:
            return records
        for line in text.splitlines():
            record = parse_line(line)
            if record and record.get("type"):
                records.append(record)
        return records

    def get_records(self) -> list[dict]:
        """Parse JSONL records from this process's stdout."""
        stdout = self.stdout
        if not stdout and self.stdout_file and self.stdout_file.exists():
            stdout = self.stdout_file.read_text(errors="replace")
        return self.parse_records_from_text(stdout or "")

    @staticmethod
    def from_json(record: dict[str, Any], overrides: dict[str, Any] | None = None):
        """
        Create/update Process from JSON dict.

        Args:
            record: JSON dict with 'id' or process details
            overrides: Optional dict of field overrides

        Returns:
            Process instance or None
        """
        process_id = record.get("id")
        if process_id:
            try:
                return Process.objects.get(id=process_id)
            except Process.DoesNotExist:
                pass
        return None

    def safe_update(self, update_fields: dict[str, Any], *, refresh: bool = True, extra_filter: dict[str, Any] | None = None) -> bool:
        """
        Compare-and-swap update for short Process scheduler writes.

        Process is not a ModelWithQueue subclass, but its scheduler methods
        still need the same modified_at CAS behavior as
        Crawl/Snapshot/Binary without falling back to save().
        """
        values = dict(update_fields)
        values.setdefault("modified_at", timezone.now())
        queryset = type(self).objects.filter(pk=self.pk, modified_at=self.modified_at)
        if extra_filter:
            queryset = queryset.filter(**extra_filter)
        updated = queryset.update(**values)
        if refresh:
            try:
                self.refresh_from_db()
            except type(self).DoesNotExist:
                pass
        return updated == 1

    def update_and_requeue(self, **kwargs) -> bool:
        """Scheduler-facing wrapper around safe_update()."""
        return self.safe_update(
            dict(kwargs),
            extra_filter={"retry_at": self.retry_at},
        )

    def mark_running(
        self,
        *,
        process_type: str | None = None,
        pwd: str | Path | None = None,
        url: str | None = None,
        worker_type: str = "",
        timeout: int | None = None,
    ) -> None:
        """Record the current process role without changing ownership state elsewhere."""
        updates = ["status", "retry_at", "modified_at"]
        self.status = self.StatusChoices.RUNNING
        self.retry_at = None
        pid_namespace = get_current_pid_namespace()
        if self.env.get(PROCESS_PID_NAMESPACE_KEY) != pid_namespace:
            self.env = {**self.env, PROCESS_PID_NAMESPACE_KEY: pid_namespace}
            updates.append("env")
        if process_type is not None and self.process_type != process_type:
            self.process_type = process_type
            updates.append("process_type")
        if worker_type and self.worker_type != worker_type:
            self.worker_type = worker_type
            updates.append("worker_type")
        if pwd is not None and self.pwd != str(pwd):
            self.pwd = str(pwd)
            updates.append("pwd")
        if url is not None and self.url != url:
            self.url = url
            updates.append("url")
        if timeout is not None and self.timeout != timeout:
            self.timeout = timeout
            updates.append("timeout")
        self.save(update_fields=updates)

    def heartbeat(self) -> None:
        """Keep a long-lived watcher visible in recent-process monitoring."""
        self.save(update_fields=["modified_at"])

    def mark_exited(self, *, exit_code: int = 0) -> None:
        """Mark a foreground/internal process row exited after command cleanup."""
        if self.status == self.StatusChoices.EXITED and self.exit_code == exit_code:
            return
        self.status = self.StatusChoices.EXITED
        self.exit_code = exit_code
        self.ended_at = self.ended_at or timezone.now()
        self.retry_at = None
        self.save(update_fields=["status", "exit_code", "ended_at", "retry_at", "modified_at"])

    # =========================================================================
    # Process.current() and hierarchy methods
    # =========================================================================

    @classmethod
    def current(cls) -> Process:
        """
        Get or create the Process record for the current OS process.

        Similar to Machine.current(), this:
        1. Checks cache for existing Process with matching PID
        2. Validates the cached Process is still valid (PID not reused)
        3. Creates new Process if needed

        IMPORTANT: Uses psutil to validate PID hasn't been reused.
        PIDs are recycled by OS, so we compare start times.
        """
        from archivebox.machine.models import Machine, NetworkInterface

        current_pid = os.getpid()

        # Fast path used by model save diagnostics and hot runner loops. A
        # cached Process object is valid when the immutable identity we wrote
        # at creation time still describes this Python process. PID reuse cannot
        # happen while this process is alive, so pid + present started_at/cmd is
        # enough here; the slower psutil validation below remains the fallback
        # for missing/stale cache.
        if (
            state._CURRENT_PROCESS
            and state._CURRENT_PROCESS.pid == current_pid
            and state._CURRENT_PROCESS.status == cls.StatusChoices.RUNNING
            and timezone.now() < state._CURRENT_PROCESS.modified_at + timedelta(seconds=PROCESS_RECHECK_INTERVAL)
            and state._CURRENT_PROCESS.started_at is not None
            and bool(state._CURRENT_PROCESS.cmd)
        ):
            return state._CURRENT_PROCESS

        machine = Machine.current()
        iface = NetworkInterface.current()

        # Check cache validity
        if state._CURRENT_PROCESS:
            # Verify: same PID, same machine, cache not expired
            if (
                state._CURRENT_PROCESS.pid == current_pid
                and state._CURRENT_PROCESS.machine_id == machine.id
                and timezone.now() < state._CURRENT_PROCESS.modified_at + timedelta(seconds=PROCESS_RECHECK_INTERVAL)
            ):
                if state._CURRENT_PROCESS.iface_id != iface.id:
                    state._CURRENT_PROCESS.iface = iface
                    state._CURRENT_PROCESS.save(update_fields=["iface", "modified_at"])
                state._CURRENT_PROCESS.ensure_log_files()
                return state._CURRENT_PROCESS
            state._CURRENT_PROCESS = None

        # Get actual process start time from OS for validation
        os_start_time = None
        if PSUTIL_AVAILABLE:
            try:
                os_proc = psutil.Process(current_pid)
                os_start_time = os_proc.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Try to find existing Process for this PID on this machine
        # Filter by: machine + PID + RUNNING + recent + start time matches
        if os_start_time:
            candidates = cls.objects.filter(
                machine=machine,
                pid=current_pid,
                status=cls.StatusChoices.RUNNING,
                started_at__gte=timezone.now() - PID_REUSE_WINDOW,
            ).order_by("-started_at")

            current_pid_namespace = get_current_pid_namespace()
            existing = next(
                (candidate for candidate in candidates if candidate.env.get(PROCESS_PID_NAMESPACE_KEY) in (None, current_pid_namespace)),
                None,
            )
            if existing and existing.started_at:
                db_start_time = existing.started_at.timestamp()
                if abs(db_start_time - os_start_time) < START_TIME_TOLERANCE:
                    state._CURRENT_PROCESS = existing
                    if existing.iface_id != iface.id:
                        existing.iface = iface
                        existing.save(update_fields=["iface", "modified_at"])
                    state._CURRENT_PROCESS.ensure_log_files()
                    return existing

        # No valid existing record - create new one
        parent = cls._find_parent_process(machine)
        process_type = cls._detect_process_type()

        # Use psutil cmdline if available (matches what proc() will validate against)
        # Otherwise fall back to sys.argv
        cmd = sys.argv
        if PSUTIL_AVAILABLE:
            try:
                os_proc = psutil.Process(current_pid)
                cmd = os_proc.cmdline()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Use psutil start time if available (more accurate than timezone.now())
        if os_start_time:
            started_at = datetime.fromtimestamp(os_start_time, tz=timezone.get_current_timezone())
        else:
            started_at = timezone.now()

        state._CURRENT_PROCESS = cls.objects.create(
            machine=machine,
            parent=parent,
            process_type=process_type,
            cmd=cmd,
            env={PROCESS_PID_NAMESPACE_KEY: get_current_pid_namespace()},
            pwd=os.getcwd(),
            pid=current_pid,
            started_at=started_at,
            status=cls.StatusChoices.RUNNING,
            iface=iface,
        )
        state._CURRENT_PROCESS.ensure_log_files()
        return state._CURRENT_PROCESS

    @classmethod
    def _find_parent_process(cls, machine: Machine | None = None) -> Process | None:
        """
        Find the parent Process record by looking up PPID.

        IMPORTANT: Validates against PID reuse by checking:
        1. Same machine (PIDs are only unique per machine)
        2. Start time matches OS process start time
        3. Process is still RUNNING and recent

        Returns None if parent is not an ArchiveBox process.
        """
        from archivebox.machine.models import Machine

        if not PSUTIL_AVAILABLE:
            return None

        ppid = os.getppid()
        machine = machine or Machine.current()

        # Get parent process start time from OS
        try:
            os_parent = psutil.Process(ppid)
            os_parent_start = os_parent.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None  # Parent process doesn't exist

        # Find matching Process record
        candidates = cls.objects.filter(
            machine=machine,
            pid=ppid,
            status=cls.StatusChoices.RUNNING,
            started_at__gte=timezone.now() - PID_REUSE_WINDOW,
        ).order_by("-started_at")

        current_pid_namespace = get_current_pid_namespace()
        for candidate in candidates:
            if candidate.env.get(PROCESS_PID_NAMESPACE_KEY) not in (None, current_pid_namespace):
                continue
            if candidate.started_at:
                db_start_time = candidate.started_at.timestamp()
                time_diff = abs(db_start_time - os_parent_start)
                if time_diff < START_TIME_TOLERANCE:
                    return candidate

        return None  # No matching ArchiveBox parent process

    @classmethod
    def _detect_process_type(cls) -> str:
        """
        Detect the type of the current process from sys.argv.

        ``archivebox add --bg`` is a fire-and-forget queue write — it does not
        run the runner or own the runtime stack — so it's classified as CLI
        instead of ADD. The ADD process_type is reserved for the foreground
        ``archivebox add`` flow that actually takes over the runtime stack via
        ``current_command(TypeChoices.ADD, ...)``. Misclassifying ``--bg`` as
        ADD makes ``runtime_stack_owner`` treat it as a newer stack owner for
        the few seconds it's alive, knocks the running ``archivebox server``
        out of leadership, and triggers a supervisord tear-down + respawn
        cycle (~5s of dead time per add). Detecting bg here at insert time
        avoids any race window where the row briefly exists as ADD before a
        higher-level demotion.
        """
        argv = [str(arg) for arg in sys.argv]
        argv_str = " ".join(argv).lower()
        executable = Path(argv[0]).name.lower() if argv else ""

        if executable == "supervisord" or any(arg.startswith("--configuration=") for arg in argv[1:]):
            return cls.TypeChoices.SUPERVISORD
        elif "runner_watch" in argv_str:
            return cls.TypeChoices.WORKER
        elif "archivebox server" in argv_str:
            return cls.TypeChoices.SERVER
        elif "archivebox update" in argv_str:
            return cls.TypeChoices.UPDATE
        elif "archivebox add" in argv_str:
            if "--bg" in sys.argv:
                return cls.TypeChoices.CLI
            return cls.TypeChoices.ADD
        elif "archivebox search" in argv_str or "archivebox list" in argv_str:
            return cls.TypeChoices.SEARCH
        elif "archivebox run" in argv_str:
            return cls.TypeChoices.ORCHESTRATOR
        elif "archivebox" in argv_str:
            return cls.TypeChoices.CLI
        else:
            return cls.TypeChoices.BINARY

    @classmethod
    def cleanup_stale_running(cls, machine: Machine | None = None) -> int:
        """
        Mark stale RUNNING processes as EXITED in the DB.

        Processes are stale if:
        - Status is RUNNING but OS process no longer exists
        - A bounded HOOK or BINARY process exceeded its timeout plus a small grace margin
        - Status is RUNNING but started_at is older than PID_REUSE_WINDOW

        Returns count of processes cleaned up.
        """
        cleaned = 0

        # Top-level commands own their lifecycle and may run in another Docker
        # PID namespace while sharing this database. Their takeover helpers
        # validate and finalize them; local psutil cannot do so safely.
        stale = cls.objects.filter(status=cls.StatusChoices.RUNNING).exclude(
            process_type__in=(cls.TypeChoices.SERVER, cls.TypeChoices.ADD, cls.TypeChoices.UPDATE),
        )
        if machine is not None:
            stale = stale.filter(machine=machine)

        # Recovery can run against damaged DB state; stream rows so a large
        # stale Process backlog cannot be materialized in memory at once.
        for proc in stale.iterator(chunk_size=100):
            shares_pid_namespace = proc.shares_pid_namespace
            if shares_pid_namespace and proc.poll() is not None:
                cleaned += 1
                continue

            is_stale = False

            if proc.started_at and proc.process_type in (cls.TypeChoices.HOOK, cls.TypeChoices.BINARY):
                timeout_seconds = max(int(proc.timeout or 0), 0)
                timeout_deadline = proc.started_at + timedelta(seconds=timeout_seconds) + PROCESS_TIMEOUT_GRACE
                if timeout_seconds > 0 and timezone.now() >= timeout_deadline:
                    is_stale = True

            # Check if too old (PID definitely reused)
            if not is_stale and proc.started_at and proc.started_at < timezone.now() - PID_REUSE_WINDOW:
                is_stale = True
            elif not is_stale and shares_pid_namespace and PSUTIL_AVAILABLE and proc.pid is not None:
                # Check if OS process still exists with matching start time
                try:
                    os_proc = psutil.Process(proc.pid)
                    if proc.started_at:
                        db_start = proc.started_at.timestamp()
                        os_start = os_proc.create_time()
                        if abs(db_start - os_start) > START_TIME_TOLERANCE:
                            is_stale = True  # PID reused by different process
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    is_stale = True  # Process no longer exists

            if is_stale:
                proc.mark_exited(
                    exit_code=proc.exit_code if proc.exit_code is not None else _default_exit_code_for_unowned_process(proc.process_type),
                )
                cleaned += 1

        return cleaned

    # =========================================================================
    # Tree traversal properties
    # =========================================================================

    @property
    def root(self) -> Process:
        """Get the root process (CLI command) of this hierarchy."""
        proc = self
        while proc.parent_id:
            proc = proc.parent
        return proc

    @property
    def ancestors(self) -> list[Process]:
        """Get all ancestor processes from parent to root."""
        ancestors = []
        proc = self.parent
        while proc:
            ancestors.append(proc)
            proc = proc.parent
        return ancestors

    @property
    def depth(self) -> int:
        """Get depth in the process tree (0 = root)."""
        return len(self.ancestors)

    def get_descendants(self, include_self: bool = False):
        """Get all descendant processes recursively."""
        if include_self:
            pks = [self.pk]
        else:
            pks = []

        children = list(self.children.values_list("pk", flat=True))
        while children:
            pks.extend(children)
            children = list(Process.objects.filter(parent_id__in=children).values_list("pk", flat=True))

        return Process.objects.filter(pk__in=pks)

    # =========================================================================
    # Validated psutil access via .proc property
    # =========================================================================

    @property
    def shares_pid_namespace(self) -> bool:
        recorded_namespace = self.env.get(PROCESS_PID_NAMESPACE_KEY)
        return recorded_namespace in (None, get_current_pid_namespace())

    @property
    def proc(self) -> psutil.Process | None:
        """
        Get validated psutil.Process for this record.

        Returns psutil.Process ONLY if:
        1. Process with this PID exists in OS
        2. OS process start time matches our started_at (within tolerance)
        3. Process is on current machine

        Returns None if:
        - PID doesn't exist (process exited)
        - PID was reused by a different process (start times don't match)
        - We're on a different machine than where process ran
        - psutil is not available

        This prevents accidentally matching a stale/recycled PID.
        """
        from archivebox.machine.models import Machine

        if not PSUTIL_AVAILABLE:
            return None

        if not self.shares_pid_namespace:
            return None

        # Can't get psutil.Process if we don't have a PID
        if not self.pid:
            return None

        # Can't validate processes on other machines
        if self.machine_id != Machine.current().id:
            return None

        try:
            os_proc = psutil.Process(self.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None  # Process no longer exists

        # Validate start time matches to prevent PID reuse confusion
        if self.started_at:
            os_start_time = os_proc.create_time()
            db_start_time = self.started_at.timestamp()

            if abs(os_start_time - db_start_time) > START_TIME_TOLERANCE:
                # PID has been reused by a different process!
                return None

        # Optionally validate command matches (extra safety)
        if self.cmd:
            try:
                os_cmdline = os_proc.cmdline()
                if os_cmdline and self.cmd:
                    db_binary = self.cmd[0] if self.cmd else ""
                    if db_binary:
                        db_binary_name = Path(db_binary).name
                        cmd_matches = any(arg == db_binary or Path(arg).name == db_binary_name for arg in os_cmdline if arg)
                        if not cmd_matches:
                            return None  # Different command, PID reused
            except (psutil.AccessDenied, psutil.ZombieProcess):
                pass  # Can't check cmdline, trust start time match

        return os_proc

    @property
    def is_running(self) -> bool:
        """
        Check if process is currently running via psutil.

        More reliable than checking status field since it validates
        the actual OS process exists and matches our record.
        """
        if not self.shares_pid_namespace:
            return self.status == self.StatusChoices.RUNNING

        proc = self.proc
        if proc is None:
            return False
        try:
            # Treat zombies as not running (they should be reaped)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
        except Exception:
            pass
        return proc.is_running()

    # =========================================================================
    # Lifecycle methods (launch, kill, poll, wait)
    # =========================================================================

    @property
    def stdout_file(self) -> Path | None:
        """Path to stdout log."""
        runtime_dir = self.runtime_dir
        return runtime_dir / "stdout.log" if runtime_dir else None

    @property
    def stderr_file(self) -> Path | None:
        """Path to stderr log."""
        runtime_dir = self.runtime_dir
        return runtime_dir / "stderr.log" if runtime_dir else None

    @property
    def hook_script_name(self) -> str | None:
        """Best-effort hook filename extracted from the process command."""
        if self.process_type != self.TypeChoices.HOOK or not self.cmd:
            return None

        for arg in self.cmd:
            arg = str(arg)
            if arg.startswith("-"):
                continue
            candidate = Path(arg).name
            if candidate.startswith("on_") and Path(candidate).suffix in {".py", ".js", ".sh"}:
                return candidate

        return None

    @property
    def runtime_dir(self) -> Path | None:
        """Directory where this process stores runtime stdout/stderr logs."""
        if not self.pwd:
            return None

        base_dir = Path(self.pwd)
        hook_name = self.hook_script_name
        if hook_name:
            return base_dir / ".hooks" / hook_name
        return base_dir

    def ensure_log_files(self) -> None:
        """Ensure stdout/stderr log files exist for this process."""
        runtime_dir = self.runtime_dir
        if not runtime_dir:
            return
        try:
            runtime_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        try:
            if self.stdout_file:
                self.stdout_file.parent.mkdir(parents=True, exist_ok=True)
                self.stdout_file.touch(exist_ok=True)
            if self.stderr_file:
                self.stderr_file.parent.mkdir(parents=True, exist_ok=True)
                self.stderr_file.touch(exist_ok=True)
        except OSError:
            return

    def kill(self, signal_num: int = 15) -> bool:
        """
        Kill this process and update status.

        Uses self.proc for safe killing - only kills if PID matches
        our recorded process (prevents killing recycled PIDs).

        Args:
            signal_num: Signal to send (default SIGTERM=15)

        Returns:
            True if killed successfully, False otherwise
        """
        if not self.shares_pid_namespace:
            return False

        # Use validated psutil.Process to ensure we're killing the right process
        proc = self.proc
        if proc is None:
            # Process doesn't exist or PID was recycled - just update status
            if self.status != self.StatusChoices.EXITED:
                self.status = self.StatusChoices.EXITED
                self.ended_at = self.ended_at or timezone.now()
                self.save()
            return False

        try:
            # Safe to kill - we validated it's our process via start time match
            proc.send_signal(signal_num)

            # Update our record
            # Use standard Unix convention: 128 + signal number
            self.exit_code = 128 + signal_num
            self.ended_at = timezone.now()
            self.status = self.StatusChoices.EXITED
            self.save()

            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            # Process already exited between proc check and kill
            self.status = self.StatusChoices.EXITED
            self.ended_at = self.ended_at or timezone.now()
            self.save()
            return False

    def poll(self) -> int | None:
        """
        Check if process has exited and update status if so.

        Cleanup when process exits:
        - Copy stdout/stderr to DB (keep files for debugging)
        - Delete PID file

        Returns:
            exit_code if exited, None if still running
        """
        if self.status == self.StatusChoices.EXITED:
            if self.exit_code == -1:
                self.exit_code = 137
                self.save(update_fields=["exit_code"])
            return self.exit_code

        if not self.is_running:
            # Reap child process if it's a zombie (best-effort)
            proc = self.proc
            if proc is not None:
                try:
                    proc.wait(timeout=0.001)
                except Exception:
                    pass
            # Process exited - read output and copy to DB
            if self.stdout_file and self.stdout_file.exists():
                self.stdout = self.stdout_file.read_text(errors="replace")
            if self.stderr_file and self.stderr_file.exists():
                self.stderr = self.stderr_file.read_text(errors="replace")

            self.exit_code = self.exit_code if self.exit_code is not None else _default_exit_code_for_unowned_process(self.process_type)
            if self.exit_code == -1:
                self.exit_code = 137
            self.ended_at = timezone.now()
            self.status = self.StatusChoices.EXITED
            self.save()
            return self.exit_code

        return None  # Still running

    def wait(self, timeout: int | None = None) -> int:
        """
        Wait for process to exit, polling periodically.

        Args:
            timeout: Max seconds to wait (None = use self.timeout)

        Returns:
            exit_code

        Raises:
            TimeoutError if process doesn't exit in time
        """
        import time

        from archivebox.config.constants import CONSTANTS

        timeout = timeout or self.timeout
        if self.process_type == self.TypeChoices.HOOK:
            timeout = min(int(timeout), int(CONSTANTS.MAX_HOOK_RUNTIME_SECONDS))
        start = time.time()

        while True:
            exit_code = self.poll()
            if exit_code is not None:
                return exit_code

            if time.time() - start > timeout:
                raise TimeoutError(f"Process {self.id} did not exit within {timeout}s")

            time.sleep(0.1)

    def terminate(self, graceful_timeout: float = 5.0) -> bool:
        """
        Gracefully terminate process: SIGTERM → wait → SIGKILL.

        This consolidates SIGTERM/SIGKILL logic used by:
        - workers/management/commands/runner_watch.py
        - workers/pid_utils.py stop_worker()
        - supervisord_util.py stop_existing_supervisord_process()

        Args:
            graceful_timeout: Seconds to wait after SIGTERM before SIGKILL

        Returns:
            True if process was terminated, False if already dead
        """
        import signal

        proc = self.proc
        if proc is None:
            # Already dead - just update status
            if self.status != self.StatusChoices.EXITED:
                self.status = self.StatusChoices.EXITED
                self.ended_at = self.ended_at or timezone.now()
                self.save()
            return False

        try:
            # Step 1: Send SIGTERM for graceful shutdown
            proc.terminate()

            # Step 2: Wait for graceful exit
            try:
                exit_status = proc.wait(timeout=graceful_timeout)
                # Process exited gracefully
                # psutil.Process.wait() returns the exit status
                self.exit_code = exit_status if exit_status is not None else 0
                self.status = self.StatusChoices.EXITED
                self.ended_at = timezone.now()
                self.save()
                return True
            except psutil.TimeoutExpired:
                pass  # Still running, need to force kill

            # Step 3: Force kill with SIGKILL
            proc.kill()
            proc.wait(timeout=2)

            # Use standard Unix convention: 128 + signal number
            self.exit_code = 128 + signal.SIGKILL
            self.status = self.StatusChoices.EXITED
            self.ended_at = timezone.now()
            self.save()
            return True

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Process already dead
            self.status = self.StatusChoices.EXITED
            self.ended_at = self.ended_at or timezone.now()
            self.save()
            return False

    def kill_tree(self, graceful_timeout: float = 2.0) -> int:
        """
        Kill this process and all its children (OS children, not DB children) in parallel.

        Uses parallel polling approach - sends SIGTERM to all processes at once,
        then polls all simultaneously with individual deadline tracking.

        This consolidates child-killing logic used by:
        - core/takeover_util.py
        - supervisord_util.py stop_existing_supervisord_process()

        Args:
            graceful_timeout: Seconds to wait after SIGTERM before SIGKILL

        Returns:
            Number of processes killed (including self)
        """
        import os
        import signal
        import time

        if not self.shares_pid_namespace:
            return 0

        killed_count = 0
        used_sigkill = False
        proc = self.proc
        if proc is None:
            # Already dead
            if self.status != self.StatusChoices.EXITED:
                self.status = self.StatusChoices.EXITED
                self.ended_at = self.ended_at or timezone.now()
                self.save()
            return 0

        try:
            # Phase 1: Get all children and send SIGTERM to entire tree in parallel
            children = proc.children(recursive=True)
            deadline = time.time() + graceful_timeout

            # Send SIGTERM to all children first (non-blocking)
            for child in children:
                try:
                    os.kill(child.pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass

            # Send SIGTERM to parent
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

            # Phase 2: Poll all processes in parallel
            all_procs = children + [proc]
            still_running = {p.pid for p in all_procs}

            while still_running and time.time() < deadline:
                time.sleep(0.1)

                for pid in list(still_running):
                    try:
                        # Check if process exited
                        os.kill(pid, 0)  # Signal 0 checks if process exists
                    except (OSError, ProcessLookupError):
                        # Process exited
                        still_running.remove(pid)
                        killed_count += 1

            # Phase 3: SIGKILL any stragglers that exceeded timeout
            if still_running:
                for pid in still_running:
                    try:
                        os.kill(pid, signal.SIGKILL)
                        killed_count += 1
                        used_sigkill = True
                    except (OSError, ProcessLookupError):
                        pass

            # Update self status
            if used_sigkill:
                self.exit_code = 128 + signal.SIGKILL
            else:
                self.exit_code = 128 + signal.SIGTERM if killed_count > 0 else 0
            self.status = self.StatusChoices.EXITED
            self.ended_at = timezone.now()
            self.save()

            return killed_count

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Process tree already dead
            self.status = self.StatusChoices.EXITED
            self.ended_at = self.ended_at or timezone.now()
            self.save()
            return killed_count

    # =========================================================================
    # Class methods for querying processes
    # =========================================================================

    @classmethod
    def get_running(cls, process_type: str | None = None, machine: Machine | None = None) -> QuerySet[Process]:
        """
        Get all running processes, optionally filtered by type.

        Replaces:
        - workers/pid_utils.py get_all_worker_pids()
        - workers/orchestrator.py get_total_worker_count()

        Args:
            process_type: Filter by TypeChoices (e.g., 'worker', 'hook')
            machine: Filter by machine (defaults to current)

        Returns:
            QuerySet of running Process records
        """
        from archivebox.machine.models import Machine

        machine = machine or Machine.current()
        qs = cls.objects.filter(
            machine=machine,
            status=cls.StatusChoices.RUNNING,
        )
        if process_type:
            qs = qs.filter(process_type=process_type)
        return qs

    @classmethod
    def get_running_count(cls, process_type: str | None = None, machine: Machine | None = None) -> int:
        """
        Get count of running processes.

        Replaces:
        - workers/pid_utils.py get_running_worker_count()
        """
        return cls.get_running(process_type=process_type, machine=machine).count()

    @classmethod
    def cleanup_orphaned_chrome(cls) -> int:
        """
        Kill orphaned Chrome processes using chrome_utils.js killZombieChrome.

        Scans DATA_DIR for chrome/*.pid files from stale crawls (>5 min old)
        and kills any orphaned Chrome processes.

        Called by:
        - Orchestrator on startup (cleanup from previous crashes)
        - Orchestrator periodically (every N minutes)

        Returns:
            Number of zombie Chrome processes killed
        """
        import subprocess
        from importlib.resources import files

        from archivebox.machine.models import Binary, BinaryManager

        chrome_utils = files("abx_plugins.plugins.chrome").joinpath("chrome_utils.js")
        if not chrome_utils.exists():
            return 0

        node_binary = cast(BinaryManager, Binary.objects).get_valid_binary("node")
        if node_binary is None or not node_binary.is_valid:
            return 0
        from archivebox.config.common import get_config

        node_projection = get_config().ABXPKG_LIB_DIR / "env" / "bin" / "node"
        if not node_projection.is_symlink() or not os.access(node_projection, os.X_OK):
            return 0

        crawl_roots = [
            crawls_dir
            for user_dir in CONSTANTS.USERS_DIR.iterdir()
            if user_dir.is_dir()
            for crawls_dir in [user_dir / "crawls"]
            if crawls_dir.is_dir()
        ]
        if not crawl_roots:
            return 0

        killed = 0
        try:
            for crawl_root in crawl_roots:
                result = subprocess.run(
                    [str(node_projection), str(chrome_utils), "killZombieChrome", str(crawl_root)],
                    capture_output=True,
                    timeout=30,
                    text=True,
                )
                if result.returncode == 0:
                    killed += int(result.stdout.strip())
            if killed > 0:
                rprint(f"[yellow]🧹 Cleaned up {killed} orphaned Chrome processes[/yellow]")
            return killed
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as e:
            rprint(f"[red]Failed to cleanup orphaned Chrome: {e}[/red]")

        return 0

    @classmethod
    def cleanup_orphaned_workers(cls) -> int:
        """
        Mark orphaned worker/hook processes as EXITED in the DB.

        Orphaned if:
        - Root (orchestrator/cli) is not running, or
        - No orchestrator/cli ancestor exists.

        Standalone worker runs (archivebox run --snapshot-id) are allowed.
        """
        cleaned = 0

        running_children = cls.objects.filter(
            process_type__in=[cls.TypeChoices.WORKER, cls.TypeChoices.HOOK],
            status=cls.StatusChoices.RUNNING,
        )

        # Recovery can run against damaged DB state; stream rows so a large
        # orphaned Process backlog cannot be materialized in memory at once.
        for proc in running_children.iterator(chunk_size=100):
            if not proc.is_running:
                proc.mark_exited(
                    exit_code=proc.exit_code if proc.exit_code is not None else _default_exit_code_for_unowned_process(proc.process_type),
                )
                cleaned += 1
                continue

            root = proc.root
            # Standalone worker/hook process (run directly)
            if root.id == proc.id and root.process_type in (cls.TypeChoices.WORKER, cls.TypeChoices.HOOK):
                continue

            # If root is an active ArchiveBox command/orchestrator, keep it.
            if (
                root.process_type
                in (
                    cls.TypeChoices.ORCHESTRATOR,
                    cls.TypeChoices.SERVER,
                    cls.TypeChoices.UPDATE,
                    cls.TypeChoices.ADD,
                    cls.TypeChoices.SEARCH,
                    cls.TypeChoices.CLI,
                )
                and root.is_running
            ):
                continue

            proc.mark_exited(
                exit_code=proc.exit_code if proc.exit_code is not None else _default_exit_code_for_unowned_process(proc.process_type),
            )
            cleaned += 1

        if cleaned:
            rprint(f"[yellow]🧹 Cleaned up {cleaned} orphaned worker/hook process record(s)[/yellow]")
        return cleaned
