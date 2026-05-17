__package__ = "archivebox.config"

import json
import re
import secrets
import sys
import shutil
from collections.abc import Mapping
from typing import Any, ClassVar, cast
from pathlib import Path

from rich.console import Console
from pydantic import BaseModel, Field, create_model, field_validator, model_validator
from pydantic_settings import SettingsConfigDict
from abx_plugins.plugins.base.utils import BASE_CONFIG_PATH, build_config_model, resolve_plugin_configs

from archivebox.config.configset import BaseConfigSet
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
_WARNED_SERVER_SECURITY_MODES: set[str] = set()
_WARNED_ARCHIVING_CONFIGS: set[tuple[int, bool]] = set()


def rprint(*args, file=None, **kwargs):
    console = _STDERR_CONSOLE if file is sys.stderr else _STDOUT_CONSOLE
    console.print(*args, **kwargs)


class ShellConfig(BaseConfigSet):
    toml_section_header: str = "SHELL_CONFIG"

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

    # ARCHIVE_DIR / USERS_DIR are resolved dynamically via get_config().
    ARCHIVE_DIR: Path = Field(default=CONSTANTS.ARCHIVE_DIR)
    USERS_DIR: Path = Field(default=CONSTANTS.USERS_DIR)

    # TMP_DIR must be a local, fast, readable/writable dir by archivebox user,
    # must be a short path due to unix path length restrictions for socket files (<100 chars)
    # must be a local SSD/tmpfs for speed and because bind mounts/network mounts/FUSE dont support unix sockets
    TMP_DIR: Path = Field(default=CONSTANTS.DEFAULT_TMP_DIR)

    # LIB_DIR must be a local, fast, readable/writable dir by archivebox user,
    # must be able to contain executable binaries (up to 5GB size)
    # should not be a remote/network/FUSE mount for speed reasons, otherwise extractors will be slow
    LIB_DIR: Path = Field(default=CONSTANTS.DEFAULT_LIB_DIR)

    # LIB_BIN_DIR is where all installed binaries are symlinked for easy PATH management
    # Derived from LIB_DIR / 'bin', should be prepended to PATH for all hook executions
    LIB_BIN_DIR: Path = Field(default=CONSTANTS.DEFAULT_LIB_BIN_DIR)

    # CUSTOM_TEMPLATES_DIR allows users to override default templates
    # defaults to DATA_DIR / 'user_templates' but can be configured
    CUSTOM_TEMPLATES_DIR: Path = Field(default=CONSTANTS.CUSTOM_TEMPLATES_DIR)

    OUTPUT_PERMISSIONS: str = Field(default="644")
    RESTRICT_FILE_NAMES: str = Field(default="windows")
    ENFORCE_ATOMIC_WRITES: bool = Field(default=True)

    # not supposed to be user settable:
    DIR_OUTPUT_PERMISSIONS: str = Field(default="755")  # computed from OUTPUT_PERMISSIONS


class GeneralConfig(BaseConfigSet):
    toml_section_header: str = "GENERAL_CONFIG"

    TAG_SEPARATOR_PATTERN: str = Field(default=r"[,]")


class ServerConfig(BaseConfigSet):
    toml_section_header: str = "SERVER_CONFIG"

    SERVER_SECURITY_MODES: ClassVar[tuple[str, ...]] = (
        "safe-subdomains-fullreplay",
        "safe-onedomain-nojsreplay",
        "unsafe-onedomain-noadmin",
        "danger-onedomain-fullreplay",
    )

    SECRET_KEY: str = Field(default_factory=lambda: "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789_") for _ in range(50)))
    BIND_ADDR: str = Field(default="127.0.0.1:8000")
    LISTEN_HOST: str = Field(default="archivebox.localhost:8000")
    ADMIN_BASE_URL: str = Field(default="")
    ARCHIVE_BASE_URL: str = Field(default="")
    ALLOWED_HOSTS: str = Field(default="*")
    CSRF_TRUSTED_ORIGINS: str = Field(default="http://admin.archivebox.localhost:8000")
    SERVER_SECURITY_MODE: str = Field(default="safe-subdomains-fullreplay")

    SNAPSHOTS_PER_PAGE: int = Field(default=40)
    PREVIEW_ORIGINALS: bool = Field(default=True)
    FOOTER_INFO: str = Field(
        default="Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.",
    )
    # CUSTOM_TEMPLATES_DIR: Path          = Field(default=None)  # this is now a constant

    PUBLIC_INDEX: bool = Field(default=True)
    PUBLIC_SNAPSHOTS: bool = Field(default=True)
    PUBLIC_SNAPSHOTS_LIST: bool | None = Field(default=None)
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


def _print_server_security_mode_warning(config: ServerConfig) -> None:
    if not config.IS_LOWER_SECURITY_MODE:
        return
    if config.SERVER_SECURITY_MODE in _WARNED_SERVER_SECURITY_MODES:
        return

    rprint(
        f"[yellow][!] WARNING: ArchiveBox is running with SERVER_SECURITY_MODE={config.SERVER_SECURITY_MODE}[/yellow]",
        file=sys.stderr,
    )
    rprint(
        "[yellow]    Archived pages may share an origin with privileged app routes in this mode.[/yellow]",
        file=sys.stderr,
    )
    rprint(
        "[yellow]    To switch to the safer isolated setup:[/yellow]",
        file=sys.stderr,
    )
    rprint(
        "[yellow]    1. Set SERVER_SECURITY_MODE=safe-subdomains-fullreplay[/yellow]",
        file=sys.stderr,
    )
    rprint(
        "[yellow]    2. Point *.archivebox.localhost (or your chosen base domain) at this server[/yellow]",
        file=sys.stderr,
    )
    rprint(
        "[yellow]    3. Configure wildcard DNS/TLS or your reverse proxy so admin., web., api., and snapshot subdomains resolve[/yellow]",
        file=sys.stderr,
    )
    _WARNED_SERVER_SECURITY_MODES.add(config.SERVER_SECURITY_MODE)


class ArchivingConfig(BaseConfigSet):
    toml_section_header: str = "ARCHIVING_CONFIG"

    PLUGINS: str = Field(
        default="",
        description="Comma-separated plugin selection for this run. Empty means use enabled plugin defaults.",
    )
    ENABLED_PLUGINS: str = Field(
        default="",
        description="Comma-separated plugin selection override used by the UI and API.",
    )
    ENABLED_EXTRACTORS: str = Field(
        default="",
        description="Legacy comma-separated plugin selection override.",
    )

    ONLY_NEW: bool = Field(default=True)
    OVERWRITE: bool = Field(default=False)

    TIMEOUT: int = Field(default=60)
    MAX_URL_ATTEMPTS: int = Field(default=50)
    MAX_DEPTH: int = Field(default=0)
    MAX_URLS: int = Field(default=0)
    MAX_SIZE: int = Field(default=0)

    RESOLUTION: str = Field(default="1440,2000")
    CHECK_SSL_VALIDITY: bool = Field(default=True)
    USER_AGENT: str = Field(
        default=f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 ArchiveBox/{VERSION} (+https://github.com/ArchiveBox/ArchiveBox/)",
    )
    COOKIES_FILE: Path | None = Field(default=None)

    URL_DENYLIST: str = Field(default=r"\.(css|js|otf|ttf|woff|woff2|gstatic\.com|googleapis\.com/css)(\?.*)?$", alias="URL_BLACKLIST")
    URL_ALLOWLIST: str | None = Field(default=None, alias="URL_WHITELIST")

    SAVE_ALLOWLIST: dict[str, list[str]] = Field(default={})  # mapping of regex patterns to list of archive methods
    SAVE_DENYLIST: dict[str, list[str]] = Field(default={})

    DEFAULT_PERSONA: str = Field(default="Default")

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

    @property
    def URL_ALLOWLIST_PTN(self) -> re.Pattern | None:
        return re.compile(self.URL_ALLOWLIST, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS) if self.URL_ALLOWLIST else None

    @property
    def URL_DENYLIST_PTN(self) -> re.Pattern:
        return re.compile(self.URL_DENYLIST, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS)

    @property
    def SAVE_ALLOWLIST_PTNS(self) -> dict[re.Pattern, list[str]]:
        return (
            {
                # regexp: methods list
                re.compile(key, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS): val
                for key, val in self.SAVE_ALLOWLIST.items()
            }
            if self.SAVE_ALLOWLIST
            else {}
        )

    @property
    def SAVE_DENYLIST_PTNS(self) -> dict[re.Pattern, list[str]]:
        return (
            {
                # regexp: methods list
                re.compile(key, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS): val
                for key, val in self.SAVE_DENYLIST.items()
            }
            if self.SAVE_DENYLIST
            else {}
        )


class SearchBackendConfig(BaseConfigSet):
    toml_section_header: str = "SEARCH_BACKEND_CONFIG"

    USE_INDEXING_BACKEND: bool = Field(default=True)
    USE_SEARCHING_BACKEND: bool = Field(default=True)

    SEARCH_BACKEND_ENGINE: str = Field(default="ripgrep")
    SEARCH_PROCESS_HTML: bool = Field(default=True)


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

    DATA_DIR: Path = Field(default=CONSTANTS.DATA_DIR)
    ABX_RUNTIME: str = Field(default="archivebox")
    CRAWL_DIR: Path | None = Field(default=None)
    CRAWL_OUTPUT_DIR: Path | None = Field(default=None)
    SNAP_DIR: Path | None = Field(default=None)
    computed_config_keys: ClassVar[tuple[str, ...]] = COMPUTED_CONFIG_KEYS

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
    persona: Any = None,
    user: Any = None,
    crawl: Any = None,
    snapshot: Any = None,
    archiveresult: Any = None,
    machine: Any = None,
) -> ArchiveBoxBaseConfig:
    """
    Get merged config from all sources.

    Priority (highest to lowest):
    1. Explicit overrides
    2. Per-snapshot config and output path
    3. Per-crawl config and output path
    4. Per-user config
    5. Per-persona derived config
    6. Current machine derived config
    7. Environment variables
    8. Config file (ArchiveBox.conf)
    9. Plugin schema defaults
    10. Core config defaults
    """
    if snapshot is None and archiveresult is not None:
        snapshot = archiveresult.snapshot

    if crawl is None and snapshot is not None:
        crawl = snapshot.crawl

    if machine is None:
        try:
            from django.apps import apps

            if apps.ready:
                from archivebox.machine.models import Machine

                machine = Machine.current()
        except Exception:
            machine = None

    if persona is None and crawl is not None:
        from archivebox.personas.models import Persona

        persona_id = crawl.persona_id
        if persona_id:
            persona = Persona.objects.filter(id=persona_id).first()
            if persona is None:
                raise Persona.DoesNotExist(f"Crawl {crawl.id} references missing Persona {persona_id}")

        if persona is None:
            crawl_config = crawl.config or {}
            default_persona_name = str(crawl_config.get("DEFAULT_PERSONA") or "").strip()
            if default_persona_name:
                persona, _ = Persona.objects.get_or_create(name=default_persona_name or "Default")
                persona.ensure_dirs()

    config_data: ConfigPayload = dict(defaults or {})
    config_data.update(ArchiveBoxConfig().model_dump(mode="json"))

    plugin_schemas = {
        plugin_name: schema.get("properties", {}) for plugin_name, schema in PLUGIN_CONFIG_SCHEMAS.items() if isinstance(schema, dict)
    }

    scope_overrides: ConfigPayload = {}

    if machine is not None and machine.config:
        from archivebox.machine.models import _sanitize_machine_config

        scope_overrides.update(_sanitize_machine_config(machine.config))

    if persona is not None:
        scope_overrides.update(persona.get_derived_config())

    if user is not None and user.config:
        scope_overrides.update(user.config)

    if crawl is not None and crawl.config:
        scope_overrides.update(crawl.config)

    if crawl is not None:
        scope_overrides["CRAWL_OUTPUT_DIR"] = crawl.output_dir
        scope_overrides["CRAWL_DIR"] = crawl.output_dir

    if snapshot is not None and snapshot.config:
        scope_overrides.update(snapshot.config)

    if snapshot is not None:
        scope_overrides["SNAP_DIR"] = snapshot.output_dir

    if overrides:
        scope_overrides.update(overrides)

    archivebox_scope_overrides = {key: value for key, value in scope_overrides.items() if key in _archivebox_config_input_names()}
    config_data.update(archivebox_scope_overrides)

    plugin_global_config = {key: str(value) if isinstance(value, Path) else value for key, value in config_data.items()}
    plugin_sections = resolve_plugin_configs(
        plugin_schemas,
        global_config=plugin_global_config,
        user_config={**BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE), **_plugin_user_config(scope_overrides)},
    )
    for plugin_config in plugin_sections.values():
        config_data.update(plugin_config)
    config_data.update(archivebox_scope_overrides)

    config_data["ABX_RUNTIME"] = "archivebox"

    config = ArchiveBoxConfig.model_validate(config_data)
    archiving_warning_key = (config.TIMEOUT, config.USE_COLOR)
    if archiving_warning_key not in _WARNED_ARCHIVING_CONFIGS:
        config.warn_if_invalid()
        _WARNED_ARCHIVING_CONFIGS.add(archiving_warning_key)
    _print_server_security_mode_warning(config)
    return config


def get_all_configs() -> dict[str, BaseConfigSet]:
    """Get all config section objects as a dictionary."""
    return {
        "SHELL_CONFIG": ShellConfig(),
        "STORAGE_CONFIG": StorageConfig(),
        "GENERAL_CONFIG": GeneralConfig(),
        "SERVER_CONFIG": ServerConfig(),
        "ARCHIVING_CONFIG": ArchivingConfig(),
        "SEARCH_BACKEND_CONFIG": SearchBackendConfig(),
        "LDAP_CONFIG": LDAPConfig(),
    }
