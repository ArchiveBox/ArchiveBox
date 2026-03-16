"""
Persona management for ArchiveBox.

A Persona represents a browser profile/identity used for archiving.
Each persona has its own:
- Chrome user data directory (for cookies, localStorage, extensions, etc.)
- Chrome extensions directory
- Cookies file
- Config overrides
"""

__package__ = 'archivebox.personas'

import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from django.db import models
from django.conf import settings
from django.utils import timezone

from archivebox.base_models.models import ModelWithConfig, get_or_create_system_user_pk
from archivebox.uuid_compat import uuid7

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

if TYPE_CHECKING:
    pass


VOLATILE_PROFILE_DIR_NAMES = {
    'Cache',
    'Code Cache',
    'GPUCache',
    'ShaderCache',
    'Service Worker',
    'GCM Store',
    'Crashpad',
    'BrowserMetrics',
}

VOLATILE_PROFILE_FILE_NAMES = {
    'BrowserMetrics-spare.pma',
    'SingletonCookie',
    'SingletonLock',
    'SingletonSocket',
}


class Persona(ModelWithConfig):
    """
    Browser persona/profile for archiving sessions.

    Each persona provides:
    - CHROME_USER_DATA_DIR: Chrome profile directory
    - CHROME_EXTENSIONS_DIR: Installed extensions directory
    - CHROME_DOWNLOADS_DIR: Chrome downloads directory
    - COOKIES_FILE: Cookies file for wget/curl
    - config: JSON field with persona-specific config overrides

    Usage:
        # Get persona and its derived config
        config = get_config(persona=crawl.persona, crawl=crawl, snapshot=snapshot)
        chrome_dir = config['CHROME_USER_DATA_DIR']

        # Or access directly from persona
        persona = Persona.objects.get(name='Default')
        persona.CHROME_USER_DATA_DIR  # -> Path to chrome_user_data
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    name = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk)

    class Meta:
        app_label = 'personas'

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
        return str(self.path / 'chrome_user_data')

    @property
    def CHROME_EXTENSIONS_DIR(self) -> str:
        """Derived path to Chrome extensions directory for this persona."""
        return str(self.path / 'chrome_extensions')

    @property
    def CHROME_DOWNLOADS_DIR(self) -> str:
        """Derived path to Chrome downloads directory for this persona."""
        return str(self.path / 'chrome_downloads')

    @property
    def COOKIES_FILE(self) -> str:
        """Derived path to cookies.txt file for this persona (if exists)."""
        cookies_path = self.path / 'cookies.txt'
        return str(cookies_path) if cookies_path.exists() else ''

    def get_derived_config(self) -> dict:
        """
        Get config dict with derived paths filled in.

        Returns dict with:
        - All values from self.config JSONField
        - CHROME_USER_DATA_DIR (derived from persona path)
        - CHROME_EXTENSIONS_DIR (derived from persona path)
        - CHROME_DOWNLOADS_DIR (derived from persona path)
        - COOKIES_FILE (derived from persona path, if file exists)
        - ACTIVE_PERSONA (set to this persona's name)
        """
        derived = dict(self.config or {})

        # Add derived paths (don't override if explicitly set in config)
        if 'CHROME_USER_DATA_DIR' not in derived:
            derived['CHROME_USER_DATA_DIR'] = self.CHROME_USER_DATA_DIR
        if 'CHROME_EXTENSIONS_DIR' not in derived:
            derived['CHROME_EXTENSIONS_DIR'] = self.CHROME_EXTENSIONS_DIR
        if 'CHROME_DOWNLOADS_DIR' not in derived:
            derived['CHROME_DOWNLOADS_DIR'] = self.CHROME_DOWNLOADS_DIR
        if 'COOKIES_FILE' not in derived and self.COOKIES_FILE:
            derived['COOKIES_FILE'] = self.COOKIES_FILE

        # Always set ACTIVE_PERSONA to this persona's name
        derived['ACTIVE_PERSONA'] = self.name

        return derived

    def ensure_dirs(self) -> None:
        """Create persona directories if they don't exist."""
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / 'chrome_user_data').mkdir(parents=True, exist_ok=True)
        (self.path / 'chrome_extensions').mkdir(parents=True, exist_ok=True)
        (self.path / 'chrome_downloads').mkdir(parents=True, exist_ok=True)

    def cleanup_chrome_profile(self, profile_dir: Path) -> bool:
        """Remove volatile Chrome state that should never be reused across launches."""
        cleaned = False

        if not profile_dir.exists():
            return False

        for path in profile_dir.rglob('*'):
            if path.name in VOLATILE_PROFILE_FILE_NAMES:
                try:
                    path.unlink()
                    cleaned = True
                except OSError:
                    pass

        for dirname in VOLATILE_PROFILE_DIR_NAMES:
            for path in profile_dir.rglob(dirname):
                if not path.is_dir():
                    continue
                shutil.rmtree(path, ignore_errors=True)
                cleaned = True

        for path in profile_dir.rglob('*.log'):
            try:
                path.unlink()
                cleaned = True
            except OSError:
                pass

        return cleaned

    def cleanup_chrome(self) -> bool:
        """Clean up volatile Chrome state for this persona's base profile."""
        return self.cleanup_chrome_profile(self.path / 'chrome_user_data')

    @contextmanager
    def lock_runtime_for_crawl(self):
        lock_path = self.path / '.archivebox-crawl-profile.lock'
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        with lock_path.open('w') as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def runtime_root_for_crawl(self, crawl) -> Path:
        return Path(crawl.output_dir) / '.persona' / self.name

    def runtime_profile_dir_for_crawl(self, crawl) -> Path:
        return self.runtime_root_for_crawl(crawl) / 'chrome_user_data'

    def runtime_downloads_dir_for_crawl(self, crawl) -> Path:
        return self.runtime_root_for_crawl(crawl) / 'chrome_downloads'

    def copy_chrome_profile(self, source_dir: Path, destination_dir: Path) -> None:
        destination_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(destination_dir, ignore_errors=True)
        destination_dir.mkdir(parents=True, exist_ok=True)

        copy_cmd: list[str] | None = None
        source_contents = f'{source_dir}/.'

        if sys.platform == 'darwin':
            copy_cmd = ['cp', '-cR', source_contents, str(destination_dir)]
        elif sys.platform.startswith('linux'):
            copy_cmd = ['cp', '-a', source_contents, str(destination_dir)]

        if copy_cmd:
            result = subprocess.run(copy_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return

            shutil.rmtree(destination_dir, ignore_errors=True)
            destination_dir.mkdir(parents=True, exist_ok=True)

        shutil.copytree(source_dir, destination_dir, symlinks=True, dirs_exist_ok=True)

    def prepare_runtime_for_crawl(self, crawl, chrome_binary: str = '') -> dict[str, str]:
        self.ensure_dirs()

        template_dir = Path(self.CHROME_USER_DATA_DIR)
        runtime_root = self.runtime_root_for_crawl(crawl)
        runtime_profile_dir = self.runtime_profile_dir_for_crawl(crawl)
        runtime_downloads_dir = self.runtime_downloads_dir_for_crawl(crawl)

        with self.lock_runtime_for_crawl():
            if not runtime_profile_dir.exists():
                if template_dir.exists() and any(template_dir.iterdir()):
                    self.copy_chrome_profile(template_dir, runtime_profile_dir)
                else:
                    runtime_profile_dir.mkdir(parents=True, exist_ok=True)

            runtime_downloads_dir.mkdir(parents=True, exist_ok=True)
            self.cleanup_chrome_profile(runtime_profile_dir)

            (runtime_root / 'persona_name.txt').write_text(self.name)
            (runtime_root / 'template_dir.txt').write_text(str(template_dir))
            if chrome_binary:
                (runtime_root / 'chrome_binary.txt').write_text(chrome_binary)

        return {
            'CHROME_USER_DATA_DIR': str(runtime_profile_dir),
            'CHROME_DOWNLOADS_DIR': str(runtime_downloads_dir),
        }

    def cleanup_runtime_for_crawl(self, crawl) -> None:
        shutil.rmtree(Path(crawl.output_dir) / '.persona', ignore_errors=True)

    @classmethod
    def get_or_create_default(cls) -> 'Persona':
        """Get or create the Default persona."""
        persona, _ = cls.objects.get_or_create(name='Default')
        return persona

    @classmethod
    def cleanup_chrome_all(cls) -> int:
        """Clean up Chrome state files for all personas."""
        cleaned = 0
        for persona in cls.objects.all():
            if persona.cleanup_chrome():
                cleaned += 1
        return cleaned
