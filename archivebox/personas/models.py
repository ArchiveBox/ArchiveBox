"""
Persona management for ArchiveBox.

A Persona represents a browser profile/identity used for archiving.
Each persona has its own:
- Chrome user data directory (for cookies, localStorage, extensions, etc.)
- Chrome extensions directory
- Cookies file
- Config overrides

Personas are stored as directories under PERSONAS_DIR (default: data/personas/).
"""

__package__ = 'archivebox.personas'

from pathlib import Path
from typing import Optional, Dict, Any, Iterator


class Persona:
    """
    Represents a browser persona/profile for archiving sessions.

    Each persona is a directory containing:
    - chrome_user_data/     Chrome profile directory
    - chrome_extensions/    Installed extensions
    - cookies.txt           Cookies file for wget/curl
    - config.json           Persona-specific config overrides

    Usage:
        persona = Persona('Default')
        persona.cleanup_chrome()

        # Or iterate all personas:
        for persona in Persona.all():
            persona.cleanup_chrome()
    """

    def __init__(self, name: str, personas_dir: Optional[Path] = None):
        """
        Initialize a Persona by name.

        Args:
            name: Persona name (directory name under PERSONAS_DIR)
            personas_dir: Override PERSONAS_DIR (defaults to CONSTANTS.PERSONAS_DIR)
        """
        self.name = name

        if personas_dir is None:
            from archivebox.config.constants import CONSTANTS
            personas_dir = CONSTANTS.PERSONAS_DIR

        self.personas_dir = Path(personas_dir)
        self.path = self.personas_dir / name

    @property
    def chrome_user_data_dir(self) -> Path:
        """Path to Chrome user data directory for this persona."""
        return self.path / 'chrome_user_data'

    @property
    def chrome_extensions_dir(self) -> Path:
        """Path to Chrome extensions directory for this persona."""
        return self.path / 'chrome_extensions'

    @property
    def cookies_file(self) -> Path:
        """Path to cookies.txt file for this persona."""
        return self.path / 'cookies.txt'

    @property
    def config_file(self) -> Path:
        """Path to config.json file for this persona."""
        return self.path / 'config.json'

    @property
    def singleton_lock(self) -> Path:
        """Path to Chrome's SingletonLock file."""
        return self.chrome_user_data_dir / 'SingletonLock'

    def exists(self) -> bool:
        """Check if persona directory exists."""
        return self.path.is_dir()

    def ensure_dirs(self) -> None:
        """Create persona directories if they don't exist."""
        self.path.mkdir(parents=True, exist_ok=True)
        self.chrome_user_data_dir.mkdir(parents=True, exist_ok=True)
        self.chrome_extensions_dir.mkdir(parents=True, exist_ok=True)

    def cleanup_chrome(self) -> bool:
        """
        Clean up Chrome state files for this persona.

        Removes stale SingletonLock files left behind when Chrome crashes
        or is killed unexpectedly. This allows Chrome to start fresh.

        Returns:
            True if cleanup was performed, False if no cleanup needed
        """
        cleaned = False

        # Remove SingletonLock if it exists
        if self.singleton_lock.exists():
            try:
                self.singleton_lock.unlink()
                cleaned = True
            except OSError:
                pass  # May be in use by active Chrome

        # Also clean up any other stale lock files Chrome might leave
        if self.chrome_user_data_dir.exists():
            for lock_file in self.chrome_user_data_dir.glob('**/SingletonLock'):
                try:
                    lock_file.unlink()
                    cleaned = True
                except OSError:
                    pass

            # Clean up socket files
            for socket_file in self.chrome_user_data_dir.glob('**/SingletonSocket'):
                try:
                    socket_file.unlink()
                    cleaned = True
                except OSError:
                    pass

        return cleaned

    def get_config(self) -> Dict[str, Any]:
        """
        Load persona-specific config overrides from config.json.

        Returns:
            Dict of config overrides, or empty dict if no config file
        """
        import json

        if not self.config_file.exists():
            return {}

        try:
            return json.loads(self.config_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def save_config(self, config: Dict[str, Any]) -> None:
        """
        Save persona-specific config overrides to config.json.

        Args:
            config: Dict of config overrides to save
        """
        import json

        self.ensure_dirs()
        self.config_file.write_text(json.dumps(config, indent=2))

    @classmethod
    def all(cls, personas_dir: Optional[Path] = None) -> Iterator['Persona']:
        """
        Iterate over all personas in PERSONAS_DIR.

        Args:
            personas_dir: Override PERSONAS_DIR (defaults to CONSTANTS.PERSONAS_DIR)

        Yields:
            Persona instances for each persona directory
        """
        if personas_dir is None:
            from archivebox.config.constants import CONSTANTS
            personas_dir = CONSTANTS.PERSONAS_DIR

        personas_dir = Path(personas_dir)

        if not personas_dir.exists():
            return

        for persona_path in personas_dir.iterdir():
            if persona_path.is_dir():
                yield cls(persona_path.name, personas_dir)

    @classmethod
    def get_active(cls) -> 'Persona':
        """
        Get the currently active persona based on ACTIVE_PERSONA config.

        Returns:
            Persona instance for the active persona
        """
        from archivebox.config.configset import get_config

        config = get_config()
        active_name = config.get('ACTIVE_PERSONA', 'Default')
        return cls(active_name)

    @classmethod
    def cleanup_chrome_all(cls, personas_dir: Optional[Path] = None) -> int:
        """
        Clean up Chrome state files for all personas.

        Args:
            personas_dir: Override PERSONAS_DIR (defaults to CONSTANTS.PERSONAS_DIR)

        Returns:
            Number of personas that had cleanup performed
        """
        cleaned_count = 0
        for persona in cls.all(personas_dir):
            if persona.cleanup_chrome():
                cleaned_count += 1
        return cleaned_count

    def __str__(self) -> str:
        return f"Persona({self.name})"

    def __repr__(self) -> str:
        return f"Persona(name={self.name!r}, path={self.path!r})"


# Convenience functions for use without instantiating Persona class

def cleanup_chrome_for_persona(name: str, personas_dir: Optional[Path] = None) -> bool:
    """
    Clean up Chrome state files for a specific persona.

    Args:
        name: Persona name
        personas_dir: Override PERSONAS_DIR (defaults to CONSTANTS.PERSONAS_DIR)

    Returns:
        True if cleanup was performed, False if no cleanup needed
    """
    return Persona(name, personas_dir).cleanup_chrome()


def cleanup_chrome_all_personas(personas_dir: Optional[Path] = None) -> int:
    """
    Clean up Chrome state files for all personas.

    Args:
        personas_dir: Override PERSONAS_DIR (defaults to CONSTANTS.PERSONAS_DIR)

    Returns:
        Number of personas that had cleanup performed
    """
    return Persona.cleanup_chrome_all(personas_dir)
