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
    scope: str = "global",
    defaults: Optional[Dict] = None,
    user: Any = None,
    crawl: Any = None,
    snapshot: Any = None,
) -> Dict[str, Any]:
    """
    Get merged config from all sources.

    Priority (highest to lowest):
    1. Per-snapshot config (snapshot.config JSON field)
    2. Per-crawl config (crawl.config JSON field)
    3. Per-user config (user.config JSON field)
    4. Environment variables
    5. Config file (ArchiveBox.conf)
    6. Plugin schema defaults (config.json)
    7. Core config defaults

    Args:
        scope: Config scope ('global', 'crawl', 'snapshot', etc.)
        defaults: Default values to start with
        user: User object with config JSON field
        crawl: Crawl object with config JSON field
        snapshot: Snapshot object with config JSON field

    Returns:
        Merged config dict
    """
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

    # Override with environment variables
    for key in config:
        env_val = os.environ.get(key)
        if env_val is not None:
            config[key] = _parse_env_value(env_val, config.get(key))

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

    # Apply user config overrides
    if user and hasattr(user, "config") and user.config:
        config.update(user.config)

    # Apply crawl config overrides
    if crawl and hasattr(crawl, "config") and crawl.config:
        config.update(crawl.config)

    # Apply snapshot config overrides (highest priority)
    if snapshot and hasattr(snapshot, "config") and snapshot.config:
        config.update(snapshot.config)

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
    return get_config(scope="global")


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
    "archive_org": 2,
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
