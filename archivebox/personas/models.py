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

from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from django.db import models
from django.conf import settings
from django.utils import timezone

from archivebox.base_models.models import ModelWithConfig, get_or_create_system_user_pk
from archivebox.uuid_compat import uuid7

if TYPE_CHECKING:
    from django.db.models import QuerySet


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

    def cleanup_chrome(self) -> bool:
        """
        Clean up Chrome state files (SingletonLock, etc.) for this persona.

        Returns:
            True if cleanup was performed, False if no cleanup needed
        """
        cleaned = False
        chrome_dir = self.path / 'chrome_user_data'

        if not chrome_dir.exists():
            return False

        # Clean up SingletonLock files
        for lock_file in chrome_dir.glob('**/SingletonLock'):
            try:
                lock_file.unlink()
                cleaned = True
            except OSError:
                pass

        # Clean up SingletonSocket files
        for socket_file in chrome_dir.glob('**/SingletonSocket'):
            try:
                socket_file.unlink()
                cleaned = True
            except OSError:
                pass

        return cleaned

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
