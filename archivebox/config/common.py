from __future__ import annotations

__package__ = "archivebox.config"

import json
import os
import re
import secrets
import sys
import shutil
from functools import lru_cache
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, ClassVar, cast
from pathlib import Path

from rich.console import Console
from pydantic import BaseModel, Field, PrivateAttr, create_model, field_validator, model_validator
from pydantic_settings import SettingsConfigDict
from abx_plugins.plugins.base.utils import BASE_CONFIG_PATH, build_config_model, resolve_plugin_configs

from archivebox.config.configset import BaseConfigSet, IniConfigSettingsSource
from archivebox.config.configset import COMPUTED_CONFIG_KEYS

from .constants import CONSTANTS
from .ldap import LDAPConfig
from .version import get_COMMIT_HASH, get_BUILD_TIME, VERSION
from .permissions import IN_DOCKER

ConfigOverrides = Mapping[str, object]
ConfigPayload = dict[str, object]
PluginSchemaDocuments = dict[str, dict[str, Any]]

###################### Config ##########################

_STDOUT_CONSOLE = Console()
_STDERR_CONSOLE = Console(stderr=True)
_WARNED_ARCHIVING_CONFIGS: set[tuple[int, bool]] = set()


def _legacy_bool(value: object) -> bool | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def permissions_from_legacy_public_flags(raw_config: Mapping[str, object]) -> str | None:
    if str(raw_config.get("PERMISSIONS") or "").strip():
        return None

    public_snapshots = _legacy_bool(raw_config.get("PUBLIC_SNAPSHOTS"))
    public_index = _legacy_bool(raw_config.get("PUBLIC_INDEX"))
    if public_snapshots is False:
        return "private"
    if public_index is False:
        return "unlisted"
    if public_snapshots is True or public_index is True:
        return "public"
    return None


_SENSITIVE_CONFIG_KEY_NEEDLES = ("TOKEN", "SECRET", "API_KEY", "APIKEY", "PASSWORD")
SENSITIVE_CONFIG_VALUE_REDACTED = "********"
_SCOPE_CRAWL_FROZEN = "crawl_frozen"
_SCOPE_CRAWL_EXECUTION = "crawl_execution"
_SCOPE_SERVER = "server"



def _plugin_sensitive_config_keys() -> set[str]:
    sensitive_keys: set[str] = set()
    for prop_key, prop_schema in _plugin_config_properties(PLUGIN_CONFIG_SCHEMAS).items():
        if isinstance(prop_schema, Mapping) and prop_schema.get("x-sensitive"):
            sensitive_keys.add(str(prop_key))
    return sensitive_keys


def is_sensitive_config_key(key: str) -> bool:
    """True if a config key names a credential and must be write-only in the UI.

    Matches any key whose uppercase form contains ``TOKEN``, ``SECRET``,
    ``API_KEY``, ``APIKEY``, or ``PASSWORD`` — covers ``SECRET_KEY``,
    ``OPENAI_API_KEY``, ``TWOCAPTCHA_APIKEY``, ``GITHUB_TOKEN``,
    ``ADMIN_PASSWORD``, etc. Centralized here so the KeyValueWidget
    (Machine/Crawl/Snapshot/Persona admin forms), the plugin config grid,
    REST API responses, and any future surface that round-trips raw config
    values all agree on which keys to redact.
    """
    key = str(key or "")
    upper = key.upper()
    return key in _plugin_sensitive_config_keys() or any(needle in upper for needle in _SENSITIVE_CONFIG_KEY_NEEDLES)


def redact_sensitive_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copy of ``config`` with credential values replaced by ``********``.

    Used wherever a config dict crosses an API/export/debug-dump boundary. The
    widget-side write-only treatment handles the form-render path; this helper
    handles every JSON-response path (REST schemas, ``to_json`` exports, admin
    debug views, etc.). Empty values are passed through unchanged so callers
    can still tell "unset" from "set-but-hidden."
    """
    if config is None:
        return {}
    if not isinstance(config, Mapping):
        return {}
    redacted: dict[str, Any] = {}
    for key, value in config.items():
        if is_sensitive_config_key(str(key)) and value not in (None, ""):
            redacted[key] = SENSITIVE_CONFIG_VALUE_REDACTED
        else:
            redacted[key] = value
    return redacted



def normalize_runtime_config(config: BaseConfigSet | Mapping[str, Any] | str | None) -> dict[str, Any]:
    """Return a JSON-safe config dict suitable for storage or event payloads."""
    if config is None:
        return {}
    if isinstance(config, BaseConfigSet):
        config = config.model_dump(mode="json")
    elif isinstance(config, str):
        config = json.loads(config)
    else:
        config = dict(config)
    return {key: value for key, value in json.loads(json.dumps(config, default=str)).items() if value is not None}


def build_crawl_config_snapshot(
    *,
    user: Any = None,
    persona: Any = None,
    overrides: Mapping[str, Any] | None = None,
    base_config: ArchiveBoxBaseConfig | Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build the frozen runtime config stored on Crawl.config at creation time."""
    effective = get_config(user=user, persona=persona, base_config=base_config, include_machine=False)
    frozen = effective.for_crawl_frozen()
    if overrides:
        frozen = get_config(base_config=frozen, overrides=overrides, include_machine=False).for_crawl_frozen()
    return frozen

def rprint(*args, file=None, **kwargs):
    console = _STDERR_CONSOLE if file is sys.stderr else _STDOUT_CONSOLE
    console.print(*args, **kwargs)


class ShellConfig(BaseConfigSet):
    toml_section_header: str = "SHELL_CONFIG"
    _scope: str = PrivateAttr(default=_SCOPE_CRAWL_EXECUTION)

    DEBUG: bool = Field(default="--debug" in sys.argv)

    IS_TTY: bool = Field(default=sys.stdout.isatty())
    USE_COLOR: bool = Field(default=sys.stdout.isatty())
    SHOW_PROGRESS: bool = Field(default=sys.stdout.isatty())

    IN_DOCKER: bool = Field(default=IN_DOCKER)
    IN_QEMU: bool = Field(default=False)

    ANSI: dict[str, str] = Field(
        default_factory=lambda: CONSTANTS.DEFAULT_CLI_COLORS if sys.stdout.isatty() else CONSTANTS.DISABLED_CLI_COLORS,
    )

    @property
    def TERM_WIDTH(self) -> int:
        if not self.IS_TTY:
            return 200
        return shutil.get_terminal_size((140, 10)).columns

    @property
    def COMMIT_HASH(self) -> str | None:
        return get_COMMIT_HASH()

    @property
    def BUILD_TIME(self) -> str:
        return get_BUILD_TIME()


class StorageConfig(BaseConfigSet):
    toml_section_header: str = "STORAGE_CONFIG"
    _scope: str = PrivateAttr(default=_SCOPE_SERVER)

    # ARCHIVE_DIR / USERS_DIR are resolved dynamically via get_config().
    ARCHIVE_DIR: Path = Field(default=CONSTANTS.ARCHIVE_DIR)
    USERS_DIR: Path = Field(default=CONSTANTS.USERS_DIR)
    PERSONAS_DIR: Path = Field(default=CONSTANTS.PERSONAS_DIR)

    # TMP_DIR must be a local, fast, readable/writable dir by archivebox user,
    # must be a short path due to unix path length restrictions for socket files (<100 chars)
    # must be a local SSD/tmpfs for speed and because bind mounts/network mounts/FUSE dont support unix sockets
    TMP_DIR: Path = Field(default=CONSTANTS.DEFAULT_TMP_DIR, json_schema_extra={"scope": _SCOPE_CRAWL_EXECUTION})

    # LIB_DIR must be a local, fast, readable/writable dir by archivebox user,
    # must be able to contain executable binaries (up to 5GB size)
    # should not be a remote/network/FUSE mount for speed reasons, otherwise extractors will be slow
    LIB_DIR: Path = Field(default=CONSTANTS.DEFAULT_LIB_DIR, json_schema_extra={"scope": _SCOPE_CRAWL_EXECUTION})

    # LIB_BIN_DIR is an optional human-facing symlink convenience directory.
    # Runtime lookup must use provider-specific paths under LIB_DIR instead.
    LIB_BIN_DIR: Path = Field(default=CONSTANTS.DEFAULT_LIB_BIN_DIR, json_schema_extra={"scope": _SCOPE_CRAWL_EXECUTION})

    # CUSTOM_TEMPLATES_DIR allows users to override default templates
    # defaults to DATA_DIR / 'user_templates' but can be configured
    CUSTOM_TEMPLATES_DIR: Path = Field(default=CONSTANTS.CUSTOM_TEMPLATES_DIR)

    OUTPUT_PERMISSIONS: str = Field(default="644", json_schema_extra={"scope": _SCOPE_CRAWL_EXECUTION})
    ENFORCE_ATOMIC_WRITES: bool = Field(default=True)
    ALLOW_NO_UNIX_SOCKETS: bool = Field(default=False, alias="ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS")


class GeneralConfig(BaseConfigSet):
    toml_section_header: str = "GENERAL_CONFIG"
    _scope: str = PrivateAttr(default=_SCOPE_SERVER)

    TAG_SEPARATOR_PATTERN: str = Field(default=r"[,]")


class ServerConfig(BaseConfigSet):
    toml_section_header: str = "SERVER_CONFIG"
    _scope: str = PrivateAttr(default=_SCOPE_SERVER)

    SERVER_SECURITY_MODES: ClassVar[tuple[str, ...]] = (
        "safe-subdomains-fullreplay",
        "safe-onedomain-nojsreplay",
        "unsafe-onedomain-noadmin",
        "danger-onedomain-fullreplay",
    )

    SECRET_KEY: str = Field(default_factory=lambda: "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789_") for _ in range(50)))
    BIND_ADDR: str = Field(default="127.0.0.1:8000")
    BASE_URL: str = Field(default="")
    ALLOWED_HOSTS: str = Field(default="*")
    CSRF_TRUSTED_ORIGINS: str = Field(default="")
    SERVER_SECURITY_MODE: str = Field(default="safe-subdomains-fullreplay")

    SNAPSHOTS_PER_PAGE: int = Field(default=50, ge=1)
    FOOTER_INFO: str = Field(
        default="Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.",
    )
    # CUSTOM_TEMPLATES_DIR: Path          = Field(default=None)  # this is now a constant

    PUBLIC_INDEX: bool = Field(default=True)
    PUBLIC_ADD_VIEW: bool = Field(default=False)

    ADMIN_USERNAME: str | None = Field(default=None)
    ADMIN_PASSWORD: str | None = Field(default=None)

    REVERSE_PROXY_USER_HEADER: str = Field(default="Remote-User")
    REVERSE_PROXY_WHITELIST: str = Field(default="")
    LOGOUT_REDIRECT_URL: str = Field(default="/")

    @field_validator("SERVER_SECURITY_MODE", mode="after")
    def validate_server_security_mode(cls, v: str) -> str:
        mode = (v or "").strip().lower()
        if mode not in cls.SERVER_SECURITY_MODES:
            raise ValueError(f"SERVER_SECURITY_MODE must be one of: {', '.join(cls.SERVER_SECURITY_MODES)}")
        return mode

    @property
    def USES_SUBDOMAIN_ROUTING(self) -> bool:
        return self.SERVER_SECURITY_MODE == "safe-subdomains-fullreplay"

    @property
    def ENABLES_FULL_JS_REPLAY(self) -> bool:
        return self.SERVER_SECURITY_MODE in (
            "safe-subdomains-fullreplay",
            "unsafe-onedomain-noadmin",
            "danger-onedomain-fullreplay",
        )

    @property
    def CONTROL_PLANE_ENABLED(self) -> bool:
        return self.SERVER_SECURITY_MODE != "unsafe-onedomain-noadmin"

    @property
    def BLOCK_UNSAFE_METHODS(self) -> bool:
        return self.SERVER_SECURITY_MODE == "unsafe-onedomain-noadmin"

    @property
    def SHOULD_NEUTER_RISKY_REPLAY(self) -> bool:
        return self.SERVER_SECURITY_MODE == "safe-onedomain-nojsreplay"

    @property
    def IS_UNSAFE_MODE(self) -> bool:
        return self.SERVER_SECURITY_MODE == "unsafe-onedomain-noadmin"

    @property
    def IS_DANGEROUS_MODE(self) -> bool:
        return self.SERVER_SECURITY_MODE == "danger-onedomain-fullreplay"

    @property
    def IS_LOWER_SECURITY_MODE(self) -> bool:
        return self.SERVER_SECURITY_MODE in (
            "unsafe-onedomain-noadmin",
            "danger-onedomain-fullreplay",
        )


class DatabaseConfig(BaseConfigSet):
    toml_section_header: str = "DATABASE_CONFIG"
    _scope: str = PrivateAttr(default=_SCOPE_SERVER)

    DATABASE_NAME: str = Field(default=str(CONSTANTS.DATABASE_FILE), alias="ARCHIVEBOX_DATABASE_NAME")
    SQLITE_JOURNAL_MODE: str = Field(
        default="WAL",
        alias="ARCHIVEBOX_SQLITE_JOURNAL_MODE",
        pattern=r"(?i)^(DELETE|TRUNCATE|PERSIST|MEMORY|WAL|OFF)$",
    )
    SQLITE_MMAP_SIZE: int = Field(
        default=0 if CONSTANTS.IN_DOCKER else 134217728,
        alias="ARCHIVEBOX_SQLITE_MMAP_SIZE",
        ge=0,
    )
    SQLITE_BUSY_TIMEOUT: int = Field(default=30000, alias="ARCHIVEBOX_SQLITE_BUSY_TIMEOUT", ge=0)
    SQLITE_LOCK_RETRY_TIMEOUT: float = Field(default=60.0, alias="ARCHIVEBOX_SQLITE_LOCK_RETRY_TIMEOUT", ge=0)
    SQLITE_LOCK_RETRY_INTERVAL: float = Field(default=5.0, alias="ARCHIVEBOX_SQLITE_LOCK_RETRY_INTERVAL", gt=0)


class ArchivingConfig(BaseConfigSet):
    toml_section_header: str = "ARCHIVING_CONFIG"
    _scope: str = PrivateAttr(default=_SCOPE_CRAWL_FROZEN)

    PLUGINS: str = Field(
        default="",
        description="Comma-separated plugin selection for this run. Empty means use enabled plugin defaults.",
    )

    ONLY_NEW: bool = Field(default=True)
    INDEX_ONLY: bool = Field(default=False)

    TIMEOUT: int = Field(default=60)
    CRAWL_MAX_URLS: int = Field(default=0)
    CRAWL_MAX_SIZE: int = Field(default=0)
    CRAWL_TIMEOUT: int = Field(default=0, description="Maximum total crawl runtime in seconds (0 = unlimited).")
    CRAWL_MAX_CONCURRENT_SNAPSHOTS: int = Field(
        default=4,
        description="Maximum number of snapshots to archive concurrently within one crawl.",
    )
    SNAPSHOT_MAX_SIZE: int = Field(default=0)

    RESOLUTION: str = Field(default="1440,2000")
    CHECK_SSL_VALIDITY: bool = Field(default=True)
    USER_AGENT: str = Field(
        default=f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 ArchiveBox/{VERSION} (+https://github.com/ArchiveBox/ArchiveBox/)",
    )
    COOKIES_FILE: Path | None = Field(default=None)

    URL_DENYLIST: str = Field(default=r"\.(css|js|otf|ttf|woff|woff2|gstatic\.com|googleapis\.com/css)(\?.*)?$", alias="URL_BLACKLIST")
    URL_ALLOWLIST: str | None = Field(default=None, alias="URL_WHITELIST")

    DEFAULT_PERSONA: str = Field(default="Default")
    PERMISSIONS: str = Field(
        default="public",
        description="Snapshot visibility: public lists and serves content, unlisted serves direct links only, private requires admin login.",
    )
    DELETE_AFTER: str = Field(
        default="0",
        description=(
            "Automatically delete Crawl, Snapshot, ArchiveResult, and Process rows after this duration. "
            "Use 0, '', or None to disable. Allowed units: h/hr/hour, d/day, w/week, mo/month, y/year; "
            "minimum non-zero duration is 1h."
        ),
    )

    def warn_if_invalid(self) -> None:
        if int(self.TIMEOUT) < 5:
            rprint(f"[red][!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={self.TIMEOUT} seconds)[/red]", file=sys.stderr)
            rprint("    You must allow *at least* 5 seconds for indexing and archive methods to run successfully.", file=sys.stderr)
            rprint("    (Setting it to somewhere between 30 and 3000 seconds is recommended)", file=sys.stderr)
            rprint(file=sys.stderr)
            rprint("    If you want to make ArchiveBox run faster, disable specific archive methods instead:", file=sys.stderr)
            rprint("        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#archive-method-toggles", file=sys.stderr)
            rprint(file=sys.stderr)

    @field_validator("CHECK_SSL_VALIDITY", mode="after")
    def validate_check_ssl_validity(cls, v):
        """SIDE EFFECT: disable "you really shouldnt disable ssl" warnings emitted by requests"""
        if not v:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return v

    @field_validator("DELETE_AFTER", mode="before")
    @classmethod
    def validate_delete_after(cls, value):
        parse_delete_after(value)
        if value is None:
            return "0"
        return str(value).strip() or "0"

    @field_validator("PERMISSIONS", mode="before")
    @classmethod
    def validate_permissions(cls, value):
        normalized = str(value or "public").strip().lower()
        if normalized not in {"public", "unlisted", "private"}:
            raise ValueError("PERMISSIONS must be one of: public, unlisted, private.")
        return normalized

    @property
    def URL_ALLOWLIST_PTN(self) -> re.Pattern | None:
        return re.compile(self.URL_ALLOWLIST, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS) if self.URL_ALLOWLIST else None

    @property
    def URL_DENYLIST_PTN(self) -> re.Pattern:
        return re.compile(self.URL_DENYLIST, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS)


def parse_delete_after(value) -> timedelta | None:
    if value is None:
        return None

    raw = str(value).strip().lower()
    if raw in ("", "0", "none", "false", "no", "off"):
        return None

    match = re.fullmatch(r"(\d+)\s*(h|hr|hrs|hour|hours|d|day|days|w|week|weeks|mo|month|months|y|yr|yrs|year|years)", raw)
    if not match:
        raise ValueError("DELETE_AFTER must be 0 or a duration like 1h, 7d, 4w, 6mo, or 1y.")

    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        return None
    if unit in ("h", "hr", "hrs", "hour", "hours"):
        duration = timedelta(hours=amount)
    elif unit in ("d", "day", "days"):
        duration = timedelta(days=amount)
    elif unit in ("w", "week", "weeks"):
        duration = timedelta(weeks=amount)
    elif unit in ("mo", "month", "months"):
        duration = timedelta(days=30 * amount)
    else:
        duration = timedelta(days=365 * amount)

    if duration < timedelta(hours=1):
        raise ValueError("DELETE_AFTER must be 0 or at least 1h.")
    return duration


class SearchBackendConfig(BaseConfigSet):
    toml_section_header: str = "SEARCH_BACKEND_CONFIG"
    _scope: str = PrivateAttr(default=_SCOPE_SERVER)

    SEARCH_BACKEND_ENGINE: str = Field(default="ripgrep")


def _plugin_user_config_value(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (dict, list, bool, int, float)) or value is None:
        return json.dumps(value)
    return str(value)


def _plugin_user_config(config: Mapping[str, object]) -> dict[str, str]:
    return {key: _plugin_user_config_value(value) for key, value in config.items()}


def _discover_plugin_config_schemas() -> PluginSchemaDocuments:
    from archivebox.hooks import discover_plugin_configs

    schemas: PluginSchemaDocuments = {}
    if BASE_CONFIG_PATH.exists():
        schemas["base"] = {
            "properties": json.loads(BASE_CONFIG_PATH.read_text()).get("properties", {}),
        }
    schemas.update(discover_plugin_configs())
    return schemas


def _plugin_config_properties(plugin_schemas: PluginSchemaDocuments) -> dict[str, dict[str, Any]]:
    properties: dict[str, dict[str, Any]] = {}
    for schema in plugin_schemas.values():
        schema_properties = schema.get("properties") or {}
        if isinstance(schema_properties, dict):
            properties.update(schema_properties)
    return properties


def _plugin_config_model(plugin_schemas: PluginSchemaDocuments) -> type[BaseModel]:
    return build_config_model("ArchiveBoxPluginConfig", _plugin_config_properties(plugin_schemas))


@lru_cache(maxsize=1)
def _archivebox_config_input_names() -> set[str]:
    names = set(ArchiveBoxConfig.model_fields)
    for field in ArchiveBoxConfig.model_fields.values():
        if isinstance(field.alias, str):
            names.add(field.alias)
    return names


class ArchiveBoxBaseConfig(
    ShellConfig,
    StorageConfig,
    GeneralConfig,
    ServerConfig,
    DatabaseConfig,
    ArchivingConfig,
    SearchBackendConfig,
    LDAPConfig,
):
    """Merged, typed ArchiveBox config.

    Core ArchiveBox fields are declared above. Plugin-owned fields are added to
    the concrete ArchiveBoxConfig model from plugin JSONSchema below, so
    ArchiveBox does not hardcode any individual plugin config names.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        validate_default=True,
        use_enum_values=True,
        arbitrary_types_allowed=True,
        populate_by_name=True,
    )

    DATA_DIR: Path = Field(default=CONSTANTS.DATA_DIR, json_schema_extra={"scope": _SCOPE_CRAWL_EXECUTION})
    ABX_RUNTIME: str = Field(default="archivebox", json_schema_extra={"scope": _SCOPE_CRAWL_EXECUTION})
    CRAWL_DIR: Path | None = Field(default=None, json_schema_extra={"scope": _SCOPE_CRAWL_EXECUTION})
    SNAP_DIR: Path | None = Field(default=None, json_schema_extra={"scope": _SCOPE_CRAWL_EXECUTION})
    computed_config_keys: ClassVar[tuple[str, ...]] = COMPUTED_CONFIG_KEYS

    @classmethod
    def _core_config_classes(cls) -> tuple[type[BaseConfigSet], ...]:
        return (
            ShellConfig,
            StorageConfig,
            GeneralConfig,
            ServerConfig,
            DatabaseConfig,
            ArchivingConfig,
            SearchBackendConfig,
            LDAPConfig,
        )

    @classmethod
    def _core_field_scope(cls, key: str) -> str | None:
        if key == "toml_section_header":
            return _SCOPE_SERVER
        for config_cls in cls._core_config_classes():
            field = config_cls.model_fields.get(key)
            if field is None:
                continue
            default_scope = str(config_cls.__private_attributes__["_scope"].default)
            extra = field.json_schema_extra
            if isinstance(extra, dict) and "scope" in extra:
                return str(extra["scope"])
            return default_scope
        if key in ArchiveBoxBaseConfig.model_fields:
            field = ArchiveBoxBaseConfig.model_fields[key]
            extra = field.json_schema_extra
            if isinstance(extra, dict) and "scope" in extra:
                return str(extra["scope"])
            return _SCOPE_SERVER
        return None

    @classmethod
    def _plugin_field_scope(cls, key: str) -> str | None:
        for plugin_name, schema in PLUGIN_CONFIG_SCHEMAS.items():
            properties = schema.get("properties") if isinstance(schema, dict) else None
            if not isinstance(properties, dict) or key not in properties:
                continue
            prop_schema = properties.get(key) or {}
            if isinstance(prop_schema, Mapping) and prop_schema.get("x-scope"):
                return str(prop_schema["x-scope"])
            if str(plugin_name).startswith("search_backend_"):
                return _SCOPE_SERVER
            upper = key.upper()
            if (
                upper == "PATH"
                or upper.endswith("_PATH")
                or upper.endswith("_DIR")
                or upper.endswith("_BINARY")
                or upper.endswith("_CACHE")
                or upper.endswith("_COVERAGE")
                or upper.endswith("_PYTHON")
            ):
                return _SCOPE_CRAWL_EXECUTION
            return _SCOPE_CRAWL_FROZEN
        return None

    @classmethod
    def scope_for_key(cls, key: str) -> str:
        return cls._core_field_scope(key) or cls._plugin_field_scope(key) or _SCOPE_SERVER

    def _scoped_config(self, *, include_execution: bool) -> dict[str, Any]:
        allowed_scopes = {_SCOPE_CRAWL_FROZEN}
        if include_execution:
            allowed_scopes.add(_SCOPE_CRAWL_EXECUTION)
        return {
            key: value
            for key, value in normalize_runtime_config(self).items()
            if type(self).scope_for_key(key) in allowed_scopes
        }

    def for_crawl_execution(self) -> dict[str, Any]:
        """Config safe to pass to crawl/snapshot hook execution."""
        return self._scoped_config(include_execution=True)

    def for_crawl_frozen(self) -> dict[str, Any]:
        """Config safe to persist permanently on Crawl.config."""
        return self._scoped_config(include_execution=False)

    @model_validator(mode="after")
    def resolve_runtime_paths(self):
        self.DATA_DIR = self.DATA_DIR.expanduser().resolve()

        archive_dir = self.ARCHIVE_DIR.expanduser()
        if archive_dir == (CONSTANTS.DATA_DIR / CONSTANTS.ARCHIVE_DIR_NAME) and self.DATA_DIR != CONSTANTS.DATA_DIR:
            archive_dir = self.DATA_DIR / CONSTANTS.ARCHIVE_DIR_NAME
        if not archive_dir.is_absolute():
            archive_dir = self.DATA_DIR / archive_dir
        self.ARCHIVE_DIR = archive_dir.resolve()

        users_dir = self.USERS_DIR.expanduser()
        if users_dir == (CONSTANTS.ARCHIVE_DIR / CONSTANTS.USERS_DIR_NAME):
            users_dir = self.ARCHIVE_DIR / CONSTANTS.USERS_DIR_NAME
        if not users_dir.is_absolute():
            users_dir = self.ARCHIVE_DIR / users_dir
        self.USERS_DIR = users_dir.resolve()

        lib_dir = self.LIB_DIR.expanduser()
        if not lib_dir.is_absolute():
            lib_dir = self.DATA_DIR / lib_dir
        self.LIB_DIR = lib_dir.resolve()

        lib_bin_dir = self.LIB_BIN_DIR.expanduser()
        if lib_bin_dir == CONSTANTS.DEFAULT_LIB_BIN_DIR and self.LIB_DIR != CONSTANTS.DEFAULT_LIB_DIR:
            lib_bin_dir = self.LIB_DIR / "bin"
        elif not lib_bin_dir.is_absolute():
            lib_bin_dir = self.DATA_DIR / lib_bin_dir
        self.LIB_BIN_DIR = lib_bin_dir.resolve()

        return self


def _build_archivebox_config_model(plugin_schemas: PluginSchemaDocuments) -> type[ArchiveBoxBaseConfig]:
    core_fields = set(ArchiveBoxBaseConfig.model_fields)
    plugin_fields: dict[str, Any] = {
        key: (field.annotation, field) for key, field in _plugin_config_model(plugin_schemas).model_fields.items() if key not in core_fields
    }
    return cast(
        type[ArchiveBoxBaseConfig],
        create_model(
            "ArchiveBoxConfig",
            __base__=ArchiveBoxBaseConfig,
            __module__=__name__,
            **plugin_fields,
        ),
    )


PLUGIN_CONFIG_SCHEMAS = _discover_plugin_config_schemas()
ArchiveBoxConfig = _build_archivebox_config_model(PLUGIN_CONFIG_SCHEMAS)


def get_config(
    defaults: ConfigOverrides | None = None,
    overrides: ConfigOverrides | None = None,
    base_config: ArchiveBoxBaseConfig | Mapping[str, object] | None = None,
    persona: Any = None,
    user: Any = None,
    crawl: Any = None,
    snapshot: Any = None,
    archiveresult: Any = None,
    machine: Any = None,
    include_machine: bool = True,
    resolve_plugins: bool = True,
) -> ArchiveBoxBaseConfig:
    """
    Get merged config from all sources.

    Priority (highest to lowest):
    1. Explicit overrides
    2. Per-ArchiveResult config
    3. Per-snapshot config and output path
    4. Frozen per-crawl config and output path
    5. Per-user config (only when resolving outside a crawl)
    6. Per-persona derived config (only when resolving outside a crawl)
    7. Current machine derived config (only when resolving outside a crawl)
    8. Environment variables (only when resolving outside a crawl)
    9. Config file (ArchiveBox.conf, only when resolving outside a crawl)
    10. Plugin schema defaults
    11. Core config defaults
    """
    if snapshot is None and archiveresult is not None:
        snapshot = archiveresult.snapshot

    if crawl is None and snapshot is not None:
        crawl = snapshot.crawl

    crawl_config_base = crawl is not None and base_config is None

    if include_machine and machine is None and not crawl_config_base:
        try:
            from django.apps import apps

            if apps.ready:
                from archivebox.machine.models import Machine

                machine = Machine.current()
        except Exception:
            machine = None

    if persona is None and crawl is not None and not crawl_config_base:
        persona = crawl.resolve_persona()

    config_data: ConfigPayload = dict(defaults or {})
    base_config_payload: ConfigPayload = {}
    if crawl_config_base:
        config_data.update(dict(crawl.config or {}))
    elif base_config is not None:
        if isinstance(base_config, ArchiveBoxBaseConfig):
            base_config_payload.update(base_config.model_dump(mode="json"))
        else:
            base_config_payload.update(dict(base_config))
        config_data.update(base_config_payload)
    else:
        config_data.update(ArchiveBoxConfig().model_dump(mode="json"))
        legacy_permissions = permissions_from_legacy_public_flags({**BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE), **os.environ})
        if legacy_permissions:
            config_data["PERMISSIONS"] = legacy_permissions

    scope_overrides: ConfigPayload = {}

    if not crawl_config_base:
        if include_machine and machine is not None and machine.config:
            from archivebox.machine.models import _sanitize_machine_config

            scope_overrides.update(_sanitize_machine_config(machine.config, lib_dir=config_data.get("LIB_DIR")))

        if persona is not None:
            scope_overrides.update(persona.get_derived_config())

    if crawl is not None and crawl.config and not crawl_config_base:
        scope_overrides.update(crawl.config)

    if crawl is not None:
        if not overrides or "CRAWL_DIR" not in overrides:
            scope_overrides["CRAWL_DIR"] = crawl.output_dir

    if snapshot is not None and snapshot.config:
        scope_overrides.update(snapshot.config)

    if snapshot is not None:
        scope_overrides["SNAP_DIR"] = snapshot.output_dir

    if archiveresult is not None and archiveresult.config:
        scope_overrides.update(archiveresult.config)

    if overrides:
        scope_overrides.update(overrides)

    legacy_scope_permissions = permissions_from_legacy_public_flags(scope_overrides)
    if legacy_scope_permissions:
        scope_overrides["PERMISSIONS"] = legacy_scope_permissions

    archivebox_scope_overrides = {key: value for key, value in scope_overrides.items() if key in _archivebox_config_input_names()}
    config_data.update(archivebox_scope_overrides)

    if resolve_plugins:
        plugin_schemas = {
            plugin_name: schema.get("properties", {}) for plugin_name, schema in PLUGIN_CONFIG_SCHEMAS.items() if isinstance(schema, dict)
        }
        plugin_global_config = {key: str(value) if isinstance(value, Path) else value for key, value in config_data.items()}
        plugin_user_config = _plugin_user_config(scope_overrides)
        if not crawl_config_base:
            plugin_user_config = {**BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE), **plugin_user_config}
        plugin_sections = resolve_plugin_configs(
            plugin_schemas,
            global_config=plugin_global_config,
            user_config=plugin_user_config,
        )
        for plugin_config in plugin_sections.values():
            config_data.update(plugin_config)
        if base_config_payload:
            config_data.update({key: value for key, value in base_config_payload.items() if key in _archivebox_config_input_names()})
        if crawl_config_base:
            config_data.update(dict(crawl.config or {}))
        config_data.update(archivebox_scope_overrides)

    config_data["ABX_RUNTIME"] = "archivebox"

    # Decode JSON-encoded complex values (dict/list fields) that came from
    # string-only sources before validation. ``IniConfigSettingsSource`` does
    # this for the ArchiveBox.conf path, but Machine.config (mirrored from the
    # INI via ``_coerce_to_str_dict``) and plugin/env scope overrides bypass
    # pydantic-settings sources entirely — they feed JSON strings directly
    # into ``model_validate``, which rejects ``"{...}"`` for a ``dict[str, str]``
    # field. Run pydantic-settings' own complex-value decoder here so every
    # source converges on the same shape before validation.
    _complex_decoder = IniConfigSettingsSource(ArchiveBoxConfig)
    for _field_name, _field in ArchiveBoxConfig.model_fields.items():
        if _field_name not in config_data:
            continue
        _raw = config_data[_field_name]
        if not isinstance(_raw, str) or not _raw:
            continue
        if _complex_decoder.field_is_complex(_field):
            config_data[_field_name] = _complex_decoder.prepare_field_value(
                _field_name,
                _field,
                _raw,
                True,
            )

    config = ArchiveBoxConfig.model_validate(config_data)
    os.environ["LIB_DIR"] = str(config.LIB_DIR)
    os.environ["LIB_BIN_DIR"] = str(config.LIB_BIN_DIR)
    os.environ["ABXPKG_LIB_DIR"] = str(config.LIB_DIR)
    archiving_warning_key = (config.TIMEOUT, config.USE_COLOR)
    if archiving_warning_key not in _WARNED_ARCHIVING_CONFIGS:
        config.warn_if_invalid()
        _WARNED_ARCHIVING_CONFIGS.add(archiving_warning_key)
    return config


def get_all_configs() -> dict[str, BaseConfigSet]:
    """Get all config section objects as a dictionary."""
    return {
        "SHELL_CONFIG": ShellConfig(),
        "STORAGE_CONFIG": StorageConfig(),
        "GENERAL_CONFIG": GeneralConfig(),
        "SERVER_CONFIG": ServerConfig(),
        "DATABASE_CONFIG": DatabaseConfig(),
        "ARCHIVING_CONFIG": ArchivingConfig(),
        "SEARCH_BACKEND_CONFIG": SearchBackendConfig(),
        "LDAP_CONFIG": LDAPConfig(),
    }
