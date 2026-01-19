"""
Simplified config system for ArchiveBox.

This replaces the complex abx_spec_config/base_configset.py with a simpler
approach that still supports environment variables, config files, and
per-object overrides.
"""

__package__ = "archivebox.config"

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional, List, Type, Tuple, TYPE_CHECKING, cast
from configparser import ConfigParser

from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


class IniConfigSettingsSource(PydanticBaseSettingsSource):
    """
    Custom settings source that reads from ArchiveBox.conf (INI format).
    Flattens all sections into a single namespace.
    """

    def get_field_value(self, field: Any, field_name: str) -> Tuple[Any, str, bool]:
        config_vals = self._load_config_file()
        field_value = config_vals.get(field_name.upper())
        return field_value, field_name, False

    def __call__(self) -> Dict[str, Any]:
        return self._load_config_file()

    def _load_config_file(self) -> Dict[str, Any]:
        try:
            from archivebox.config.constants import CONSTANTS
            config_path = CONSTANTS.CONFIG_FILE
        except ImportError:
            return {}

        if not config_path.exists():
            return {}

        parser = ConfigParser()
        parser.optionxform = lambda x: x  # preserve case
        parser.read(config_path)

        # Flatten all sections into single namespace (ignore section headers)
        return {key.upper(): value for section in parser.sections() for key, value in parser.items(section)}


class BaseConfigSet(BaseSettings):
    """
    Base class for config sections.

    Automatically loads values from (highest to lowest priority):
    1. Environment variables
    2. ArchiveBox.conf file (INI format, flattened)
    3. Default values

    Subclasses define fields with defaults and types:

        class ShellConfig(BaseConfigSet):
            DEBUG: bool = Field(default=False)
            USE_COLOR: bool = Field(default=True)
    """

    model_config = ConfigDict(
        env_prefix="",
        extra="ignore",
        validate_default=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """
        Define the order of settings sources (first = highest priority).
        """
        return (
            init_settings,           # 1. Passed to __init__
            env_settings,            # 2. Environment variables
            IniConfigSettingsSource(settings_cls),  # 3. ArchiveBox.conf file
            # dotenv_settings,       # Skip .env files
            # file_secret_settings,  # Skip secrets files
        )

    @classmethod
    def load_from_file(cls, config_path: Path) -> Dict[str, str]:
        """Load config values from INI file."""
        if not config_path.exists():
            return {}

        parser = ConfigParser()
        parser.optionxform = lambda x: x  # preserve case
        parser.read(config_path)

        # Flatten all sections into single namespace
        return {key.upper(): value for section in parser.sections() for key, value in parser.items(section)}

    def update_in_place(self, warn: bool = True, persist: bool = False, **kwargs) -> None:
        """
        Update config values in place.

        This allows runtime updates to config without reloading.
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                # Use object.__setattr__ to bypass pydantic's frozen model
                object.__setattr__(self, key, value)


def get_config(
    defaults: Optional[Dict] = None,
    persona: Any = None,
    user: Any = None,
    crawl: Any = None,
    snapshot: Any = None,
    archiveresult: Any = None,
    machine: Any = None,
) -> Dict[str, Any]:
    """
    Get merged config from all sources.

    Priority (highest to lowest):
    1. Per-snapshot config (snapshot.config JSON field)
    2. Per-crawl config (crawl.config JSON field)
    3. Per-user config (user.config JSON field)
    4. Per-persona config (persona.get_derived_config() - includes CHROME_USER_DATA_DIR etc.)
    5. Environment variables
    6. Per-machine config (machine.config JSON field - resolved binary paths)
    7. Config file (ArchiveBox.conf)
    8. Plugin schema defaults (config.json)
    9. Core config defaults

    Args:
        defaults: Default values to start with
        persona: Persona object (provides derived paths like CHROME_USER_DATA_DIR)
        user: User object with config JSON field
        crawl: Crawl object with config JSON field
        snapshot: Snapshot object with config JSON field
        archiveresult: ArchiveResult object (auto-fetches snapshot)
        machine: Machine object with config JSON field (defaults to Machine.current())

    Note: Objects are auto-fetched from relationships if not provided:
        - snapshot auto-fetched from archiveresult.snapshot
        - crawl auto-fetched from snapshot.crawl
        - user auto-fetched from crawl.created_by

    Returns:
        Merged config dict
    """
    # Auto-fetch related objects from relationships
    if snapshot is None and archiveresult and hasattr(archiveresult, "snapshot"):
        snapshot = archiveresult.snapshot

    if crawl is None and snapshot and hasattr(snapshot, "crawl"):
        crawl = snapshot.crawl

    if user is None and crawl and hasattr(crawl, "created_by"):
        user = crawl.created_by
    from archivebox.config.constants import CONSTANTS
    from archivebox.config.common import (
        SHELL_CONFIG,
        STORAGE_CONFIG,
        GENERAL_CONFIG,
        SERVER_CONFIG,
        ARCHIVING_CONFIG,
        SEARCH_BACKEND_CONFIG,
    )

    # Start with defaults
    config = dict(defaults or {})

    # Add plugin config defaults from JSONSchema config.json files
    try:
        from archivebox.hooks import get_config_defaults_from_plugins
        plugin_defaults = get_config_defaults_from_plugins()
        config.update(plugin_defaults)
    except ImportError:
        pass  # hooks not available yet during early startup

    # Add all core config sections
    config.update(dict(SHELL_CONFIG))
    config.update(dict(STORAGE_CONFIG))
    config.update(dict(GENERAL_CONFIG))
    config.update(dict(SERVER_CONFIG))
    config.update(dict(ARCHIVING_CONFIG))
    config.update(dict(SEARCH_BACKEND_CONFIG))

    # Load from archivebox.config.file
    config_file = CONSTANTS.CONFIG_FILE
    if config_file.exists():
        file_config = BaseConfigSet.load_from_file(config_file)
        config.update(file_config)

    # Apply machine config overrides (cached binary paths, etc.)
    if machine is None:
        # Default to current machine if not provided
        try:
            from archivebox.machine.models import Machine
            machine = Machine.current()
        except Exception:
            pass  # Machine might not be available during early init

    if machine and hasattr(machine, "config") and machine.config:
        config.update(machine.config)

    # Override with environment variables (for keys that exist in config)
    for key in config:
        env_val = os.environ.get(key)
        if env_val is not None:
            config[key] = _parse_env_value(env_val, config.get(key))

    # Also add NEW environment variables (not yet in config)
    # This is important for worker subprocesses that receive config via Process.env
    for key, value in os.environ.items():
        if key.isupper() and key not in config:  # Only uppercase keys (config convention)
            config[key] = _parse_env_value(value, None)

    # Also check plugin config aliases in environment
    try:
        from archivebox.hooks import discover_plugin_configs
        plugin_configs = discover_plugin_configs()
        for plugin_name, schema in plugin_configs.items():
            for key, prop_schema in schema.get('properties', {}).items():
                # Check x-aliases
                for alias in prop_schema.get('x-aliases', []):
                    if alias in os.environ and key not in os.environ:
                        config[key] = _parse_env_value(os.environ[alias], config.get(key))
                        break
                # Check x-fallback
                fallback = prop_schema.get('x-fallback')
                if fallback and fallback in config and key not in config:
                    config[key] = config[fallback]
    except ImportError:
        pass

    # Apply persona config overrides (includes derived paths like CHROME_USER_DATA_DIR)
    if persona and hasattr(persona, "get_derived_config"):
        config.update(persona.get_derived_config())

    # Apply user config overrides
    if user and hasattr(user, "config") and user.config:
        config.update(user.config)

    # Apply crawl config overrides
    if crawl and hasattr(crawl, "config") and crawl.config:
        config.update(crawl.config)

    # Add CRAWL_OUTPUT_DIR for snapshot hooks to find shared Chrome session
    if crawl and hasattr(crawl, "output_dir"):
        config['CRAWL_OUTPUT_DIR'] = str(crawl.output_dir)
        config['CRAWL_ID'] = str(getattr(crawl, "id", "")) if getattr(crawl, "id", None) else config.get('CRAWL_ID')

    # Apply snapshot config overrides (highest priority)
    if snapshot and hasattr(snapshot, "config") and snapshot.config:
        config.update(snapshot.config)

    if snapshot:
        config['SNAPSHOT_ID'] = str(getattr(snapshot, "id", "")) if getattr(snapshot, "id", None) else config.get('SNAPSHOT_ID')
        config['SNAPSHOT_DEPTH'] = int(getattr(snapshot, "depth", 0) or 0)
        if getattr(snapshot, "crawl_id", None):
            config['CRAWL_ID'] = str(snapshot.crawl_id)

    # Normalize all aliases to canonical names (after all sources merged)
    # This handles aliases that came from user/crawl/snapshot configs, not just env
    try:
        from archivebox.hooks import discover_plugin_configs
        plugin_configs = discover_plugin_configs()
        aliases_to_normalize = {}  # {alias_key: canonical_key}

        # Build alias mapping from all plugin schemas
        for plugin_name, schema in plugin_configs.items():
            for canonical_key, prop_schema in schema.get('properties', {}).items():
                for alias in prop_schema.get('x-aliases', []):
                    aliases_to_normalize[alias] = canonical_key

        # Normalize: copy alias values to canonical keys (aliases take precedence)
        for alias_key, canonical_key in aliases_to_normalize.items():
            if alias_key in config:
                # Alias exists - copy to canonical key (overwriting any default)
                config[canonical_key] = config[alias_key]
                # Remove alias from config to keep it clean
                del config[alias_key]
    except ImportError:
        pass

    return config


def get_flat_config() -> Dict[str, Any]:
    """
    Get a flat dictionary of all config values.

    Replaces abx.pm.hook.get_FLAT_CONFIG()
    """
    return get_config()


def get_all_configs() -> Dict[str, BaseConfigSet]:
    """
    Get all config section objects as a dictionary.

    Replaces abx.pm.hook.get_CONFIGS()
    """
    from archivebox.config.common import (
        SHELL_CONFIG, SERVER_CONFIG, ARCHIVING_CONFIG, SEARCH_BACKEND_CONFIG
    )
    return {
        'SHELL_CONFIG': SHELL_CONFIG,
        'SERVER_CONFIG': SERVER_CONFIG,
        'ARCHIVING_CONFIG': ARCHIVING_CONFIG,
        'SEARCH_BACKEND_CONFIG': SEARCH_BACKEND_CONFIG,
    }


def _parse_env_value(value: str, default: Any = None) -> Any:
    """Parse an environment variable value based on expected type."""
    if default is None:
        # Try to guess the type
        if value.lower() in ("true", "false", "yes", "no", "1", "0"):
            return value.lower() in ("true", "yes", "1")
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
        return value

    # Parse based on default's type
    if isinstance(default, bool):
        return value.lower() in ("true", "yes", "1")
    elif isinstance(default, int):
        return int(value)
    elif isinstance(default, float):
        return float(value)
    elif isinstance(default, (list, dict)):
        return json.loads(value)
    elif isinstance(default, Path):
        return Path(value)
    else:
        return value


# Default worker concurrency settings
DEFAULT_WORKER_CONCURRENCY = {
    "crawl": 2,
    "snapshot": 3,
    "wget": 2,
    "ytdlp": 2,
    "screenshot": 3,
    "singlefile": 2,
    "title": 5,
    "favicon": 5,
    "headers": 5,
    "archivedotorg": 2,
    "readability": 3,
    "mercury": 3,
    "git": 2,
    "pdf": 2,
    "dom": 3,
}


def get_worker_concurrency() -> Dict[str, int]:
    """
    Get worker concurrency settings.

    Can be configured via WORKER_CONCURRENCY env var as JSON dict.
    """
    config = get_config()

    # Start with defaults
    concurrency = DEFAULT_WORKER_CONCURRENCY.copy()

    # Override with config
    if "WORKER_CONCURRENCY" in config:
        custom = config["WORKER_CONCURRENCY"]
        if isinstance(custom, str):
            custom = json.loads(custom)
        concurrency.update(custom)

    return concurrency
