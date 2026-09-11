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
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Mapping

from django.db import IntegrityError, models
from django.db.models.fields.json import KT
from django.conf import settings
from django.utils import timezone

from archivebox.core.permissions import PERMISSIONS_VALUES, normalize_permissions
from archivebox.base_models.models import ModelWithConfig, get_or_create_system_user_pk
from archivebox.uuid_compat import CompactUUIDField, uuid7

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


VOLATILE_PROFILE_DIR_NAMES = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "ShaderCache",
    "Crashpad",
    "BrowserMetrics",
    "Sessions",
    "Sessions_Encrypted",
}

VOLATILE_PROFILE_FILE_NAMES = {
    "BrowserMetrics-spare.pma",
    "RunningChromeVersion",
    "DevToolsActivePort",
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
    "Current Session",
    "Current Tabs",
    "Last Session",
    "Last Tabs",
}


def derive_persona_config(*, name: str, config: Mapping[str, Any] | None, persona_dir: Path) -> dict[str, Any]:
    derived = dict(config or {})
    derived["PERSONAS_DIR"] = str(persona_dir.parent)

    cookies_path = persona_dir / "cookies.txt"
    if "COOKIES_FILE" not in derived and cookies_path.exists():
        derived["COOKIES_FILE"] = str(cookies_path)

    auth_path = persona_dir / "auth.json"
    if "AUTH_STORAGE_FILE" not in derived and auth_path.exists():
        derived["AUTH_STORAGE_FILE"] = str(auth_path)

    derived["ACTIVE_PERSONA"] = name
    return derived


class Persona(ModelWithConfig):
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
        """Path to persona directory under PERSONAS_DIR."""
        from archivebox.config.constants import CONSTANTS

        return CONSTANTS.PERSONAS_DIR / self.name

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
        """Derived path to auth.json for this persona (if it exists)."""
        auth_path = self.path / "auth.json"
        return str(auth_path) if auth_path.exists() else ""

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
        return derive_persona_config(name=self.name, config=self.config, persona_dir=self.path)

    def ensure_dirs(self) -> None:
        """Create persona directories if they don't exist."""
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "chrome_profile").mkdir(parents=True, exist_ok=True)
        (self.path / "chrome_downloads").mkdir(parents=True, exist_ok=True)

    def cleanup_chrome_profile(self, profile_dir: Path) -> bool:
        """Remove volatile Chrome state that should never be reused across launches."""
        cleaned = False

        if not profile_dir.exists():
            return False

        def profile_paths():
            # Chrome profiles are user-controlled filesystem state. If a cache
            # or generated component is unreadable, cleanup should skip it and
            # continue pruning the rest instead of blocking the crawl runner.
            for dirpath, dirnames, filenames in os.walk(profile_dir, onerror=lambda _err: None):
                current_dir = Path(dirpath)
                for name in [*dirnames, *filenames]:
                    yield current_dir / name

        for path in profile_paths():
            if path.name in VOLATILE_PROFILE_FILE_NAMES:
                try:
                    path.unlink()
                    cleaned = True
                except OSError:
                    pass

        for dirname in VOLATILE_PROFILE_DIR_NAMES:
            for path in profile_paths():
                if path.name != dirname:
                    continue
                try:
                    is_dir = path.is_dir()
                except OSError:
                    is_dir = False
                if not is_dir:
                    continue
                shutil.rmtree(path, ignore_errors=True)
                cleaned = True

        for path in profile_paths():
            if path.name not in {"chrome.log", "chrome_debug.log"}:
                continue
            try:
                path.unlink()
                cleaned = True
            except OSError:
                pass

        return cleaned

    def cleanup_chrome(self) -> bool:
        """Clean up volatile Chrome state for this persona's base profile."""
        return self.cleanup_chrome_profile(self.path / "chrome_profile")

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
    def get_or_create_named(cls, name: str) -> "Persona":
        persona_name = (name or "Default").strip() or "Default"
        persona = cls.objects.filter(name=persona_name).first()
        if persona is not None:
            return persona

        try:
            return cls.objects.create(name=persona_name)
        except IntegrityError:
            return cls.objects.get(name=persona_name)

    def runtime_root_for_crawl(self, crawl) -> Path:
        return Path(crawl.output_dir) / ".persona" / self.name

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

    def copy_chrome_profile(self, source_dir: Path, destination_dir: Path) -> None:
        from archivebox.personas.importers import profile_copy_ignore

        destination_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(destination_dir, ignore_errors=True)
        shutil.copytree(
            source_dir,
            destination_dir,
            symlinks=True,
            ignore=profile_copy_ignore,
        )

    def prepare_runtime_for_crawl(self, crawl, chrome_binary: str = "") -> dict[str, str]:
        self.ensure_dirs()

        template_dir = Path(self.CHROME_USER_DATA_DIR)
        runtime_root = self.runtime_root_for_crawl(crawl)
        runtime_profile_dir = self.runtime_profile_dir_for_crawl(crawl)
        runtime_downloads_dir = self.runtime_downloads_dir_for_crawl(crawl)

        with self.lock_runtime_for_crawl():
            if runtime_root.exists():
                shutil.rmtree(runtime_root, ignore_errors=True)
            if template_dir.exists() and any(template_dir.iterdir()):
                self.copy_chrome_profile(template_dir, runtime_profile_dir)
            else:
                runtime_profile_dir.mkdir(parents=True, exist_ok=True)

            for filename in ("cookies.txt", "auth.json"):
                source = self.path / filename
                if source.is_file():
                    shutil.copy2(source, runtime_root / filename)
            runtime_downloads_dir.mkdir(parents=True, exist_ok=True)
            self.cleanup_chrome_profile(runtime_profile_dir)

            (runtime_root / "persona_name.txt").write_text(self.name)
            (runtime_root / "template_dir.txt").write_text(str(template_dir))
            if chrome_binary:
                (runtime_root / "chrome_binary.txt").write_text(chrome_binary)

        return {
            # Hooks derive CHROME_USER_DATA_DIR/CHROME_DOWNLOADS_DIR from
            # PERSONAS_DIR + ACTIVE_PERSONA. Point PERSONAS_DIR at the
            # per-crawl runtime root here so CHROME_ISOLATION=crawl never
            # leaks or reuses the template profile while keeping Chrome path
            # derivation centralized in the Chrome plugin helpers.
            "PERSONAS_DIR": str(runtime_root.parent),
            "ACTIVE_PERSONA": self.name,
            **{
                key: str(runtime_root / filename)
                for key, filename in (("COOKIES_FILE", "cookies.txt"), ("AUTH_STORAGE_FILE", "auth.json"))
                if (runtime_root / filename).is_file()
            },
        }

    def prepare_runtime_for_snapshot(self, snapshot, chrome_binary: str = "") -> dict[str, str]:
        crawl_runtime_profile_dir = self.runtime_profile_dir_for_crawl(snapshot.crawl)
        template_dir = crawl_runtime_profile_dir if crawl_runtime_profile_dir.exists() else Path(self.CHROME_USER_DATA_DIR)
        runtime_root = self.runtime_root_for_snapshot(snapshot)
        runtime_profile_dir = self.runtime_profile_dir_for_snapshot(snapshot)
        runtime_downloads_dir = self.runtime_downloads_dir_for_snapshot(snapshot)

        if runtime_root.exists():
            shutil.rmtree(runtime_root, ignore_errors=True)
        if template_dir.exists() and any(template_dir.iterdir()):
            self.copy_chrome_profile(template_dir, runtime_profile_dir)
        else:
            runtime_profile_dir.mkdir(parents=True, exist_ok=True)

        for filename in ("cookies.txt", "auth.json"):
            source = self.runtime_root_for_crawl(snapshot.crawl) / filename
            if not source.is_file():
                source = self.path / filename
            if source.is_file():
                shutil.copy2(source, runtime_root / filename)
        runtime_downloads_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup_chrome_profile(runtime_profile_dir)

        (runtime_root / "persona_name.txt").write_text(self.name)
        (runtime_root / "template_dir.txt").write_text(str(template_dir))
        if chrome_binary:
            (runtime_root / "chrome_binary.txt").write_text(chrome_binary)

        return {
            # See prepare_runtime_for_crawl(): snapshot isolation changes the
            # persona root, not individual CHROME_* config keys, so standalone
            # Chrome hooks and ArchiveBox-driven hooks resolve paths the same way.
            "PERSONAS_DIR": str(runtime_root.parent),
            "ACTIVE_PERSONA": self.name,
            **{
                key: str(runtime_root / filename)
                for key, filename in (("COOKIES_FILE", "cookies.txt"), ("AUTH_STORAGE_FILE", "auth.json"))
                if (runtime_root / filename).is_file()
            },
        }

    def cleanup_runtime_for_crawl(self, crawl) -> None:
        shutil.rmtree(Path(crawl.output_dir) / ".persona", ignore_errors=True)

    @classmethod
    def get_or_create_default(cls) -> "Persona":
        """Get or create the Default persona."""
        return cls.get_or_create_named("Default")

    @classmethod
    def cleanup_chrome_all(cls) -> int:
        """Clean up Chrome state files for all personas."""
        cleaned = 0
        for persona in cls.objects.all():
            if persona.cleanup_chrome():
                cleaned += 1
        return cleaned
