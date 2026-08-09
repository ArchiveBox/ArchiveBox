"""Pydantic-backed config loading for ArchiveBox."""

__package__ = "archivebox.config"

from pathlib import Path
from typing import Any, ClassVar
from configparser import ConfigParser

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

COMPUTED_CONFIG_KEYS = (
    "TERM_WIDTH",
    "COMMIT_HASH",
    "BUILD_TIME",
    "USES_SUBDOMAIN_ROUTING",
    "ENABLES_FULL_JS_REPLAY",
    "CONTROL_PLANE_ENABLED",
    "BLOCK_UNSAFE_METHODS",
    "SHOULD_NEUTER_RISKY_REPLAY",
    "IS_UNSAFE_MODE",
    "IS_DANGEROUS_MODE",
    "IS_LOWER_SECURITY_MODE",
    "URL_ALLOWLIST_PTN",
    "URL_DENYLIST_PTN",
)


class CaseConfigParser(ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


# ``IniConfigSettingsSource.get_field_value`` is called once per pydantic field
# (hundreds of fields across the GlobalConfig + plugin configs). Without
# caching, every field re-opens and re-parses ``ArchiveBox.conf`` from disk —
# that's the dominant cost of ``get_config()`` (each call was ~130ms; profile
# showed 632 ``parser.read(config_path)`` invocations per call). The cache is
# keyed on (path, mtime) so external edits to the file still get picked up.
_INI_CACHE: dict[tuple[str, float], dict[str, Any]] = {}


def _read_ini_config_cached(config_path_str: str) -> dict[str, Any]:
    config_path = Path(config_path_str)
    try:
        mtime = config_path.stat().st_mtime
    except (FileNotFoundError, PermissionError):
        return {}
    cache_key = (str(config_path), mtime)
    cached = _INI_CACHE.get(cache_key)
    if cached is not None:
        return cached
    parser = CaseConfigParser()
    parser.read(config_path)
    flat = {key.upper(): value for section in parser.sections() for key, value in parser.items(section)}
    _INI_CACHE.clear()
    _INI_CACHE[cache_key] = flat
    return flat


class IniConfigSettingsSource(PydanticBaseSettingsSource):
    """
    Custom settings source that reads from ArchiveBox.conf (INI format).
    Flattens all sections into a single namespace.
    """

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        config_vals = self._load_config_file()
        field_value = config_vals.get(field_name.upper())
        # Mark complex-typed fields (``dict``/``list``) so the parent
        # ``prepare_field_value`` JSON-decodes the INI string before pydantic
        # validates against the dict/list annotation. Without this, e.g.
        # ``ABX_INSTALL_CACHE`` arrives as a raw JSON string and pydantic
        # rejects it with ``Input should be a valid dictionary``.
        value_is_complex = bool(field_value is not None and self.field_is_complex(field))
        return field_value, field_name, value_is_complex

    def __call__(self) -> dict[str, Any]:
        # Use the per-field path (``get_field_value`` + ``prepare_field_value``)
        # so complex types get JSON-decoded. The previous flat-dict return
        # skipped pydantic-settings' complex-value handling entirely.
        result: dict[str, Any] = {}
        for field_name, field in self.settings_cls.model_fields.items():
            value, key, value_is_complex = self.get_field_value(field, field_name)
            if value is None:
                continue
            prepared = self.prepare_field_value(field_name, field, value, value_is_complex)
            if prepared is not None:
                result[key] = prepared
        return result

    def _load_config_file(self) -> dict[str, Any]:
        try:
            from archivebox.config.constants import CONSTANTS

            config_path = CONSTANTS.CONFIG_FILE
        except ImportError:
            return {}

        return _read_ini_config_cached(str(config_path))


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

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        validate_default=True,
        populate_by_name=True,
    )
    computed_config_keys: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """
        Define the order of settings sources (first = highest priority).
        """
        return (
            init_settings,  # 1. Passed to __init__
            env_settings,  # 2. Environment variables
            IniConfigSettingsSource(settings_cls),  # 3. ArchiveBox.conf file
            # dotenv_settings,       # Skip .env files
            # file_secret_settings,  # Skip secrets files
        )

    @classmethod
    def load_from_file(cls, config_path: Path) -> dict[str, str]:
        """Load config values from INI file."""
        if not config_path.exists():
            return {}

        parser = CaseConfigParser()
        parser.read(config_path)

        # Flatten all sections into single namespace
        return {key.upper(): value for section in parser.sections() for key, value in parser.items(section)}

    def __getitem__(self, key: str) -> Any:
        if key in type(self).model_fields:
            return getattr(self, key)
        if self.__pydantic_extra__ and key in self.__pydantic_extra__:
            return self.__pydantic_extra__[key]
        if key in self.computed_config_keys:
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key in type(self).model_fields:
            object.__setattr__(self, key, value)
            return
        if key in self.computed_config_keys:
            raise KeyError(f"{key} is computed and cannot be set")
        if self.model_config.get("extra") != "allow":
            raise KeyError(f"Unknown config key: {key}")
        extra = self.__pydantic_extra__
        if extra is None:
            extra = {}
            object.__setattr__(self, "__pydantic_extra__", extra)
        extra[key] = value

    def update(self, *args, **kwargs) -> None:
        values = dict(*args, **kwargs)
        for key, value in values.items():
            if key in self.computed_config_keys:
                continue
            self[key] = value

    def __contains__(self, key: str) -> bool:
        return (
            key in type(self).model_fields
            or bool(self.__pydantic_extra__ and key in self.__pydantic_extra__)
            or key in self.computed_config_keys
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self[key] if key in self else default

    def as_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        for key in self.computed_config_keys:
            data[key] = getattr(self, key)
        return data

    def items(self):
        return self.as_dict().items()

    def keys(self):
        return self.as_dict().keys()

    def values(self):
        return self.as_dict().values()
