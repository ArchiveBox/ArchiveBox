from __future__ import annotations

import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.db import models, transaction
from django.utils import timezone
from django.utils.functional import cached_property

from archivebox.base_models.models import ModelWithHealthStats
from archivebox.config import CONSTANTS
from archivebox.config.common import rprint
from archivebox.machine import models as state
from archivebox.uuid_compat import CompactUUIDField, uuid7
from archivebox.workers.models import ModelWithQueue

from .constants import BINARY_RECHECK_INTERVAL
from .machines import Machine


def _find_existing_binary_for_reference(machine: Machine, reference: str) -> Binary | None:
    reference = str(reference or "").strip()
    if not reference:
        return None

    qs = Binary.objects.filter(machine=machine)

    direct_match = qs.filter(abspath=reference).order_by("-modified_at").first()
    if direct_match:
        return direct_match

    ref_name = Path(reference).name
    if ref_name:
        named_match = qs.filter(name=ref_name).order_by("-modified_at").first()
        if named_match:
            return named_match

    return qs.filter(name=reference).order_by("-modified_at").first()


def _canonical_binary_name(name: Any) -> str:
    name = str(name or "").strip()
    if "/" in name or "\\" in name or name.startswith("~"):
        return Path(name).expanduser().name
    return name


class BinaryManager(models.Manager):
    def get_from_db_or_cache(self, name: str, abspath: str = "", version: str = "", sha256: str = "", binprovider: str = "env") -> Binary:
        """Get or create an Binary record from the database or cache."""
        from archivebox.machine.models import Machine

        cached = state._CURRENT_BINARIES.get(name)
        if cached and timezone.now() < cached.modified_at + timedelta(seconds=BINARY_RECHECK_INTERVAL):
            return cached
        state._CURRENT_BINARIES[name], _ = self.update_or_create(
            machine=Machine.current(),
            name=name,
            binprovider=binprovider,
            version=version,
            abspath=abspath,
            sha256=sha256,
        )
        return state._CURRENT_BINARIES[name]

    def get_valid_binary(self, name: str, machine: Machine | None = None) -> Binary | None:
        """Get a valid Binary for the given name on the current machine, or None if not found."""
        from archivebox.machine.models import Machine

        machine = machine or Machine.current()
        return (
            self.filter(
                machine=machine,
                name__iexact=name,
            )
            .exclude(abspath="")
            .exclude(abspath__isnull=True)
            .order_by("-modified_at")
            .first()
        )


class Binary(ModelWithHealthStats, ModelWithQueue):
    """
    Tracks a binary on a specific machine.

    Simple queue lifecycle with 2 states:
    - queued: Binary needs to be installed
    - installed: Binary installed successfully (abspath, version, sha256 populated)

    Installation is synchronous during queued→installed transition.
    If installation fails, Binary stays in queued with retry_at set for later retry.

    BinaryService claims queued rows with a conditional update, then run()
    emits an abxpkg BinaryRequestEvent and persists the resolved installation.
    The database row is the only lifecycle state; there is intentionally no
    second in-memory state machine to reconcile after a worker interruption.
    """

    class StatusChoices(models.TextChoices):
        QUEUED = "queued", "Queued"
        INSTALLED = "installed", "Installed"

    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, null=False)

    # Binary metadata
    name = models.CharField(max_length=63, default="", null=False, blank=True, db_index=True)
    binproviders = models.CharField(
        max_length=127,
        default="env",
        null=False,
        blank=True,
        help_text="Comma-separated list of allowed providers: apt,brew,pip,npm,env",
    )
    overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="Provider-specific overrides: {'apt': {'install_args': ['pkg']}, ...}",
    )

    # Installation results (populated after installation)
    binprovider = models.CharField(
        max_length=31,
        default="",
        null=False,
        blank=True,
        help_text="Provider that successfully installed this binary",
    )
    abspath = models.CharField(max_length=255, default="", null=False, blank=True)
    version = models.CharField(max_length=32, default="", null=False, blank=True)
    sha256 = models.CharField(max_length=64, default="", null=False, blank=True)

    # Durable queue lifecycle fields
    status = ModelWithQueue.StatusField(choices=StatusChoices.choices, default=StatusChoices.QUEUED, max_length=16)
    retry_at = ModelWithQueue.RetryAtField(
        default=timezone.now,
        help_text="When to retry this binary installation",
    )

    # Health stats
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    machine_id: uuid.UUID

    INITIAL_STATE = StatusChoices.QUEUED
    ACTIVE_STATE = StatusChoices.QUEUED
    FINAL_STATES = (StatusChoices.INSTALLED,)
    FINAL_OR_ACTIVE_STATES = (*FINAL_STATES, ACTIVE_STATE)
    active_state: str = StatusChoices.QUEUED
    warn_on_save_outside_runner = False

    objects = BinaryManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    class Meta(ModelWithHealthStats.Meta, ModelWithQueue.Meta):
        app_label = "machine"
        verbose_name = "Binary"
        verbose_name_plural = "Binaries"
        unique_together = (("machine", "name", "abspath", "version", "sha256"),)

    def __str__(self) -> str:
        return f"{self.name}@{self.binprovider}+{self.abspath}@{self.version}"

    @property
    def is_valid(self) -> bool:
        """A binary is valid if it has a resolved path and is marked installed."""
        return bool(self.abspath) and self.status == self.StatusChoices.INSTALLED

    @property
    def can_install(self) -> bool:
        return bool(self.name and self.binproviders)

    @cached_property
    def binary_info(self) -> dict:
        """Return info about the binary."""
        return {
            "name": self.name,
            "abspath": self.abspath,
            "version": self.version,
            "binprovider": self.binprovider,
            "is_valid": self.is_valid,
        }

    @property
    def output_dir(self) -> Path:
        """
        Get output directory for this binary's hook logs.
        Path: data/machines/{machine_uuid}/binaries/{binary_name}/{binary_uuid}
        """
        return CONSTANTS.DATA_DIR / "machines" / str(self.machine_id) / "binaries" / self.name / str(self.id)

    def to_json(self) -> dict:
        """
        Convert Binary model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION

        is_installed = bool(self.abspath and self.version)
        return {
            "type": "Binary" if is_installed else "BinaryRequest",
            "schema_version": VERSION,
            "id": str(self.id),
            "machine_id": str(self.machine_id),
            "name": self.name,
            "binproviders": self.binproviders,
            "overrides": self.overrides,
            "binprovider": self.binprovider,
            "abspath": self.abspath,
            "version": self.version,
            "sha256": self.sha256,
            "status": self.status,
        }

    @staticmethod
    def from_json(record: dict[str, Any], overrides: dict[str, Any] | None = None):
        """
        Create/update Binary from JSON dict.

        Handles two cases:
        1. From binaries.json: creates queued binary with name, binproviders, overrides
        2. From hook output: updates binary with abspath, version, sha256, binprovider

        Args:
            record: JSON dict with 'name' and either:
                    - 'binproviders', 'overrides' (from binaries.json)
                    - 'abspath', 'version', 'sha256', 'binprovider' (from hook output)
            overrides: Not used

        Returns:
            Binary instance or None
        """
        from archivebox.machine.models import Machine

        name = _canonical_binary_name(record.get("name"))
        if not name:
            return None

        abspath, version = record.get("abspath"), record.get("version")
        binproviders = record.get("binproviders")
        installed = bool(abspath and version) and (bool(binproviders) or "binproviders" not in record)
        if installed:
            defaults = {
                "abspath": abspath,
                "version": version,
                "sha256": record.get("sha256", ""),
                "binprovider": record.get("binprovider", "env"),
                "status": Binary.StatusChoices.INSTALLED,
                "retry_at": None,
            }
            if binproviders:
                defaults["binproviders"] = binproviders
        elif "binproviders" in record or ("overrides" in record and not abspath):
            binary_overrides = record.get("overrides", {})
            defaults = {
                "binproviders": record.get("binproviders", "env"),
                "overrides": binary_overrides if isinstance(binary_overrides, dict) else {},
                "status": Binary.StatusChoices.QUEUED,
                "retry_at": timezone.now(),
            }
        else:
            return None

        binary, _ = Binary.objects.update_or_create(machine=Machine.current(), name=name, defaults=defaults)
        if installed:
            from archivebox.config.common import get_config

            binary.symlink_to_lib_bin_after_commit(get_config().ABXPKG_LIB_DIR / "bin")
        return binary

    def _allowed_binproviders(self) -> set[str] | None:
        """Return the allowed binproviders for this binary, or None for wildcard."""
        providers = str(self.binproviders or "").strip()
        if not providers or providers == "*":
            return None
        return {provider.strip() for provider in providers.split(",") if provider.strip()}

    def run(self):
        """
        Execute binary installation through the ArchiveBox binary runner.
        """
        from archivebox.services.runner import run_binary

        run_binary(str(self.id))

    def install(self) -> bool:
        """Run one synchronous installation attempt for a claimed Binary."""
        if self.status == self.StatusChoices.INSTALLED:
            return True
        if not self.can_install:
            return False

        rprint(f"[cyan]      🔄 installing {self.name}[/cyan]", file=sys.stderr)
        self.run()
        self.refresh_from_db()
        if self.status != self.StatusChoices.INSTALLED:
            self.update_and_requeue(
                retry_at=timezone.now() + timedelta(seconds=300),
                status=self.StatusChoices.QUEUED,
            )
            self.increment_health_stats(success=False)
            raise RuntimeError(f"Binary {self.name} installation failed")

        self.update_and_requeue(retry_at=None, status=self.StatusChoices.INSTALLED)
        self.increment_health_stats(success=True)
        return True

    def advance_lifecycle(self) -> bool:
        """Advance the explicit binary lifecycle after its queue row is claimed."""
        return self.install()

    def install_claimed(self, *, lock_seconds: int = 600) -> bool:
        if not self.claim_processing_lock(lock_seconds=lock_seconds):
            return False
        self.refresh_from_db()
        return self.advance_lifecycle()

    def cleanup(self):
        """
        Clean up background binary installation hooks.

        Called after an installation attempt if needed (not typically used for binaries
        since installations are foreground, but included for consistency).
        """

        # Clean up .pid files from output directory
        output_dir = self.output_dir
        if output_dir.exists():
            for pid_file in output_dir.glob("**/*.pid"):
                pid_file.unlink(missing_ok=True)

    def symlink_to_lib_bin(self, lib_bin_dir: str | Path) -> Path | None:
        """
        Symlink this binary into a derived lib/bin directory for human-facing convenience.

        After a binary is installed by any binprovider (pip, npm, brew, apt, etc),
        we can optionally expose a flat convenience directory for shell users.
        ArchiveBox/abx-dl runtime lookup must use the provider-specific ABXPKG_LIB_DIR
        paths, not this indirection.

        Args:
            lib_bin_dir: Path to the derived convenience bin dir (e.g., /data/lib/bin)

        Returns:
            Path to the created symlink, or None if symlinking failed

        Example:
            >>> binary = Binary.objects.get(name='yt-dlp')
            >>> binary.symlink_to_lib_bin('/data/lib/arm64-darwin/bin')
            Path('/data/lib/arm64-darwin/bin/yt-dlp')
        """
        import sys
        from pathlib import Path

        if not self.abspath:
            return None

        binary_abspath = Path(self.abspath).resolve()
        lib_bin_dir = Path(lib_bin_dir).resolve()
        binary_parts = binary_abspath.parts
        try:
            app_index = next(index for index, part in enumerate(binary_parts) if part.endswith(".app"))
        except StopIteration:
            app_index = -1

        # Create the derived convenience bin dir if it doesn't exist.
        try:
            lib_bin_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            print(f"Failed to create lib/bin convenience dir {lib_bin_dir}: {e}", file=sys.stderr)
            return None

        # Expose the canonical Binary.name in the convenience bin dir. Some providers point
        # abspath at implementation files like cli.js or manifest.json; those
        # are valid targets, but they are not user-facing binary names.
        binary_name = _canonical_binary_name(self.name) or binary_abspath.name
        symlink_path = lib_bin_dir / binary_name

        if app_index != -1 and len(binary_parts) > app_index + 2 and binary_parts[app_index + 1 : app_index + 3] == ("Contents", "MacOS"):
            if symlink_path.exists() or symlink_path.is_symlink():
                try:
                    symlink_path.unlink()
                except (OSError, PermissionError) as e:
                    print(f"Failed to remove existing file at {symlink_path}: {e}", file=sys.stderr)
                    return None
            return binary_abspath

        # Remove existing symlink/file if it exists
        if symlink_path.exists() or symlink_path.is_symlink():
            try:
                # Check if it's already pointing to the right place
                if symlink_path.is_symlink() and symlink_path.resolve() == binary_abspath:
                    # Already correctly symlinked, nothing to do
                    return symlink_path

                # Remove old symlink/file
                symlink_path.unlink()
            except (OSError, PermissionError) as e:
                print(f"Failed to remove existing file at {symlink_path}: {e}", file=sys.stderr)
                return None

        # Create new symlink
        try:
            symlink_path.symlink_to(binary_abspath)
            return symlink_path
        except (OSError, PermissionError) as e:
            print(f"Failed to create symlink {symlink_path} -> {binary_abspath}: {e}", file=sys.stderr)
            return None

    def symlink_to_lib_bin_after_commit(self, lib_bin_dir: str | Path) -> None:
        """
        Symlink after the current DB transaction commits.

        Binary rows are projections of provider/hook state and are allowed to be
        updated directly, but filesystem writes must not run while an outer
        transaction is still open. Refetch after commit so the symlink points at
        the committed row, not a possibly-rolled-back in-memory value.
        """
        binary_id = self.id
        lib_bin_path = Path(lib_bin_dir)

        def create_symlink() -> None:
            binary = type(self).objects.filter(id=binary_id).first()
            if binary is not None:
                binary.symlink_to_lib_bin(lib_bin_path)

        transaction.on_commit(create_symlink)
