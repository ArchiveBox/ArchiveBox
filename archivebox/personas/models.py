"""
Persona management for ArchiveBox.

A Persona represents a browser profile/identity used for archiving.
Each persona has its own:
- Chrome user data directory (for cookies, localStorage, extensions, etc.)
- Cookies file
- Config overrides
"""

__package__ = "archivebox.personas"

import shutil
import os
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Mapping

from django.db import IntegrityError, models
from django.core.exceptions import ValidationError
from django.db.models.fields.json import KT
from django.conf import settings
from django.utils import timezone

from archivebox.core.permissions import PERMISSIONS_VALUES, normalize_permissions
from archivebox.base_models.models import ModelWithConfig, get_or_create_system_user_pk
from archivebox.uuid_compat import CompactUUIDField, compact_uuid, uuid7

_fcntl: Any | None = None
try:
    import fcntl as _fcntl_import
except ImportError:  # pragma: no cover
    pass
else:
    _fcntl = _fcntl_import

if TYPE_CHECKING:
    import fcntl
else:
    fcntl = _fcntl


def derive_persona_config(*, name: str, config: Mapping[str, Any] | None, persona_dir: Path) -> dict[str, Any]:
    derived = dict(config or {})
    derived["PERSONAS_DIR"] = str(persona_dir.parent)

    cookies_path = persona_dir / "cookies.txt"
    if "COOKIES_FILE" not in derived and cookies_path.exists():
        derived["COOKIES_FILE"] = str(cookies_path)

    auth_path = persona_dir / "auth.json"
    if "AUTH_STORAGE_FILE" not in derived:
        try:
            if auth_path.stat().st_size > 0:
                derived["AUTH_STORAGE_FILE"] = str(auth_path)
        except FileNotFoundError:
            pass

    derived["ACTIVE_PERSONA"] = name
    return derived


class Persona(ModelWithConfig):
    emoji: str = "🎭"
    """
    Browser persona/profile for archiving sessions.

    Each persona provides:
    - CHROME_USER_DATA_DIR: Chrome profile directory
    - CHROME_DOWNLOADS_DIR: Chrome downloads directory
    - COOKIES_FILE: Cookies file for wget/curl
    - config: JSON field with persona-specific config overrides

    Usage:
        # Get persona and its derived config
        config = get_config(persona=crawl.persona, crawl=crawl, snapshot=snapshot)
        chrome_dir = config['CHROME_USER_DATA_DIR']

        # Or access directly from persona
        persona = Persona.objects.get(name='Default')
        persona.CHROME_USER_DATA_DIR  # -> Path to chrome_profile
    """

    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    name = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk)
    permissions = models.GeneratedField(
        expression=KT("config__PERMISSIONS"),
        output_field=models.CharField(max_length=16, null=True),
        db_persist=True,
        db_index=True,
        editable=False,
    )

    class Meta(ModelWithConfig.Meta):
        app_label = "personas"

    def save(self, *args, **kwargs):
        # Adopt the spelling on disk, never rename a Chrome profile just to fix case.
        self.__dict__.pop("_persona_path", None)
        canonical_name = self.validate_name(self.name)
        if canonical_name != self.name:
            self.name = canonical_name
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = tuple(dict.fromkeys([*kwargs["update_fields"], "name"]))
        config = dict(self.config or {})
        if str(config.get("PERMISSIONS") or "").strip().lower() not in PERMISSIONS_VALUES:
            from archivebox.config.common import get_config

            config["PERMISSIONS"] = normalize_permissions(get_config(include_machine=True).PERMISSIONS)
            self.config = config
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = tuple(dict.fromkeys([*update_fields, "config"]))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name

    @property
    def path(self) -> Path:
        """Reuse the directory's spelling without renaming a Chrome profile."""
        from archivebox.config.constants import CONSTANTS

        cached = self.__dict__.get("_persona_path")
        if cached is None or cached[0] != self.name:
            directory_name = self.directory_name(self.name)
            cached = (self.name, CONSTANTS.PERSONAS_DIR / directory_name)
            self.__dict__["_persona_path"] = cached
        return cached[1]

    @staticmethod
    def directory_name(name: str) -> str:
        from archivebox.config.constants import CONSTANTS
        from archivebox.personas.importers import validate_persona_name

        valid, error = validate_persona_name(name)
        if not valid:
            raise ValidationError(error)
        # Linux can hold both Default/default; macOS usually aliases them. Reuse a
        # single match on either filesystem, but never guess which conflicting
        # profile contains the user's login state. Only list names, not profile trees.
        try:
            with os.scandir(CONSTANTS.PERSONAS_DIR) as entries:
                matches = sorted(entry.name for entry in entries if entry.name.casefold() == name.casefold())
        except FileNotFoundError:
            matches = []
        if len(matches) > 1:
            raise ValidationError(
                f"Conflicting persona directories: {'; '.join(str(CONSTANTS.PERSONAS_DIR / match) for match in matches)}. "
                "Stop Chrome and rename the conflicting directories manually to distinct names; no profile directories were renamed.",
            )
        return matches[0] if matches else name

    @classmethod
    def find_named(cls, name: str) -> "Persona | None":
        # SQLite's iexact is ASCII-only; Python casefold gives every entry point
        # the same Unicode matching rules as the filesystem-name lookup above.
        matches = [(pk, existing) for pk, existing in cls.objects.values_list("pk", "name") if existing.casefold() == name.casefold()]
        if len(matches) > 1:
            raise ValidationError(
                f"Conflicting persona records: {'; '.join(f'{existing!r} (ID {pk})' for pk, existing in matches)}. "
                "Rename the conflicting personas manually to distinct names; profile files have not been changed.",
            )
        return cls.objects.get(pk=matches[0][0]) if matches else None

    def validate_name(self, name: str) -> str:
        existing = self.find_named(name)
        if existing is not None and existing.pk != self.pk:
            raise ValidationError(
                f"Name conflicts with persona {existing.name!r} (ID {existing.pk}, directory {existing.path}). "
                "Choose a distinct name or rename that persona record manually.",
            )
        return self.directory_name(name)

    @property
    def CHROME_USER_DATA_DIR(self) -> str:
        """Derived path to Chrome user data directory for this persona."""
        return str(self.path / "chrome_profile")

    @property
    def CHROME_DOWNLOADS_DIR(self) -> str:
        """Derived path to Chrome downloads directory for this persona."""
        return str(self.path / "chrome_downloads")

    @property
    def COOKIES_FILE(self) -> str:
        """Derived path to cookies.txt file for this persona (if exists)."""
        cookies_path = self.path / "cookies.txt"
        return str(cookies_path) if cookies_path.exists() else ""

    @property
    def AUTH_STORAGE_FILE(self) -> str:
        """Derived path to a nonempty auth.json export for this persona."""
        auth_path = self.path / "auth.json"
        try:
            return str(auth_path) if auth_path.stat().st_size > 0 else ""
        except FileNotFoundError:
            return ""

    def get_derived_config(self) -> dict:
        """
        Get config dict with derived paths filled in.

        Returns dict with:
        - All values from self.config JSONField
        - PERSONAS_DIR (derived from DATA_DIR/personas)
        - COOKIES_FILE (derived from persona path, if file exists)
        - AUTH_STORAGE_FILE (derived from persona path, if file exists)
        - ACTIVE_PERSONA (set to this persona's name)
        """
        return derive_persona_config(name=self.path.name, config=self.config, persona_dir=self.path)

    def ensure_dirs(self) -> None:
        """Create persona directories if they don't exist."""
        # Recheck at profile preparation, including changes made outside this process.
        self.__dict__.pop("_persona_path", None)
        self.validate_name(self.name)
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "chrome_profile").mkdir(parents=True, exist_ok=True)
        (self.path / "chrome_downloads").mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock_runtime_for_crawl(self):
        lock_path = self.path / ".archivebox-crawl-profile.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        with lock_path.open("w") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @classmethod
    def get_or_create_named(cls, name: str, *, defaults: dict | None = None) -> "Persona":
        # Init/startup must reuse a user-created 'default', not create a second
        # DB row pointing at a different (or shared) profile (issue #1896).
        persona_name = (name or "Default").strip() or "Default"
        persona = cls.find_named(persona_name)
        if persona is not None:
            canonical_name = persona.validate_name(persona.name)
            if canonical_name != persona.name:
                persona.name = canonical_name
                persona.save(update_fields=["name"])
            return persona

        try:
            return cls.objects.create(name=persona_name, **(defaults or {}))
        except (IntegrityError, ValidationError):
            persona = cls.find_named(persona_name)
            if persona is None:
                raise
            persona.validate_name(persona.name)
            return persona

    def runtime_root_for_crawl(self, crawl) -> Path:
        return Path(crawl.output_dir) / ".persona" / self.name

    def local_runtime_root_for_crawl(self, crawl) -> Path:
        from archivebox.config.common import get_config

        # Browser databases, sockets, and extension directory renames require
        # local storage; archive outputs may live on an object-storage mount.
        return Path(get_config().TMP_DIR) / "personas" / str(crawl.id) / ".persona" / self.name

    def runtime_profile_dir_for_crawl(self, crawl) -> Path:
        return self.runtime_root_for_crawl(crawl) / "chrome_profile"

    def runtime_downloads_dir_for_crawl(self, crawl) -> Path:
        return self.runtime_root_for_crawl(crawl) / "chrome_downloads"

    def runtime_root_for_snapshot(self, snapshot) -> Path:
        return Path(snapshot.output_dir) / ".persona" / self.name

    def runtime_profile_dir_for_snapshot(self, snapshot) -> Path:
        return self.runtime_root_for_snapshot(snapshot) / "chrome_profile"

    def runtime_downloads_dir_for_snapshot(self, snapshot) -> Path:
        return self.runtime_root_for_snapshot(snapshot) / "chrome_downloads"

    def link_runtime_for_output(self, output_dir: Path, runtime_root: Path) -> None:
        """Keep the hook-facing .persona path while storing its contents locally."""
        link = Path(output_dir) / ".persona"
        target = runtime_root.parent
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            if link.resolve() == target.resolve():
                return
            link.unlink()
        elif link.exists():
            # Preserve pre-migration runtime files locally until crawl cleanup.
            legacy_dir = Path(tempfile.mkdtemp(prefix="legacy-persona-", dir=target.parent))
            shutil.move(str(link), str(legacy_dir / ".persona"))
        link.symlink_to(target, target_is_directory=True)

    def prepare_runtime_for_crawl(self, crawl, chrome_binary: str = "", *, use_template: bool = True) -> dict[str, str]:
        if use_template:
            self.ensure_dirs()

        template_dir = Path(self.CHROME_USER_DATA_DIR) if use_template else None
        # Traversing the archive-side symlink still invokes FUSE for every file.
        # Keep that compatibility link, but perform profile I/O directly locally.
        runtime_root = self.local_runtime_root_for_crawl(crawl)
        if template_dir is not None:
            source, destination = template_dir.resolve(), runtime_root.resolve()
            # Check before host cleanup; the plugin cannot protect a source already removed.
            if source.is_relative_to(destination) or destination.is_relative_to(source):
                raise ValueError("Source and runtime profile directories overlap")

        # Anonymous captures use the same runtime lifecycle without accessing
        # any saved persona, including its lock or authentication files.
        with self.lock_runtime_for_crawl() if use_template else nullcontext():
            runtime_root.parent.mkdir(parents=True, exist_ok=True)
            self.link_runtime_for_output(crawl.output_dir, runtime_root)
            if runtime_root.exists():
                shutil.rmtree(runtime_root, ignore_errors=True)
            from archivebox.personas.importers import run_browser_profile

            run_browser_profile(
                action="prepare",
                persona_dir=str(runtime_root),
                source_dir=str(template_dir) if template_dir is not None else None,
                name=self.name,
                browser_binary=chrome_binary,
            )

            if use_template:
                for filename in ("cookies.txt", "auth.json"):
                    source = self.path / filename
                    if source.is_file():
                        shutil.copy2(source, runtime_root / filename)
        # Hooks derive Chrome profile paths from the runtime persona root.
        # Use the same optional auth discovery as the template persona.
        return derive_persona_config(name=self.name, config={}, persona_dir=runtime_root)

    def prepare_runtime_for_snapshot(
        self,
        snapshot,
        chrome_binary: str = "",
        *,
        local_root: Path | None = None,
        use_template: bool = True,
    ) -> dict[str, str]:
        # Resolve once, rather than traversing the archive mount for every source
        # file. This also supports an existing runtime from before local storage.
        crawl_runtime_root = self.runtime_root_for_crawl(snapshot.crawl).resolve() if use_template else None
        template_dir = None
        if crawl_runtime_root is not None:
            crawl_runtime_profile_dir = crawl_runtime_root / "chrome_profile"
            template_dir = crawl_runtime_profile_dir if crawl_runtime_profile_dir.exists() else Path(self.CHROME_USER_DATA_DIR)

        # The async runner resolves config/ORM paths before entering its filesystem
        # worker; other callers retain the existing local-runtime path resolution.
        if local_root is None:
            local_root = (
                self.local_runtime_root_for_crawl(snapshot.crawl).parent.parent / "snapshots" / str(snapshot.id) / ".persona" / self.name
            )
        if template_dir is not None:
            source, destination = template_dir.resolve(), local_root.resolve()
            if source.is_relative_to(destination) or destination.is_relative_to(source):
                raise ValueError("Source and runtime profile directories overlap")
        local_root.parent.mkdir(parents=True, exist_ok=True)
        self.link_runtime_for_output(snapshot.output_dir, local_root)
        runtime_root = local_root
        if runtime_root.exists():
            shutil.rmtree(runtime_root, ignore_errors=True)
        from archivebox.personas.importers import run_browser_profile

        run_browser_profile(
            action="prepare",
            persona_dir=str(runtime_root),
            source_dir=str(template_dir) if template_dir is not None and template_dir.is_dir() else None,
            name=self.name,
            browser_binary=chrome_binary,
        )

        if crawl_runtime_root is not None:
            for filename in ("cookies.txt", "auth.json"):
                source = crawl_runtime_root / filename
                if not source.is_file():
                    source = self.path / filename
                if source.is_file():
                    shutil.copy2(source, runtime_root / filename)
        return derive_persona_config(name=self.name, config={}, persona_dir=runtime_root)

    def cleanup_runtime_for_crawl(self, crawl) -> None:
        local_root = self.local_runtime_root_for_crawl(crawl).parent.parent
        link = Path(crawl.output_dir) / ".persona"
        if link.is_symlink():
            link.unlink()
        # Snapshot isolation creates these local directories before capture.
        # They survive runner restarts and identify the archive links to remove.
        # Scanning the whole crawl instead touches every queued/historical path
        # on remote storage whenever resource pressure yields the crawl.
        snapshot_ids = []
        snapshots_dir = local_root / "snapshots"
        if snapshots_dir.is_dir():
            for directory in snapshots_dir.iterdir():
                try:
                    snapshot_ids.append(compact_uuid(directory.name))
                except ValueError:
                    continue
        for snapshot in (
            crawl.snapshot_set.filter(id__in=snapshot_ids).select_related("crawl__created_by").defer("crawl__urls").paged_iterator()
        ):
            link = Path(snapshot.output_dir) / ".persona"
            if link.is_symlink():
                link.unlink()
        shutil.rmtree(local_root, ignore_errors=True)

    @classmethod
    def get_or_create_default(cls) -> "Persona":
        """Get or create the Default persona."""
        return cls.get_or_create_named("Default")
