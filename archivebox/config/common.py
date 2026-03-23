__package__ = "archivebox.config"

import re
import sys
import shutil
from typing import ClassVar, Dict, Optional, List
from pathlib import Path

from rich import print
from pydantic import Field, field_validator
from django.utils.crypto import get_random_string

from archivebox.config.configset import BaseConfigSet

from .constants import CONSTANTS
from .version import get_COMMIT_HASH, get_BUILD_TIME, VERSION
from .permissions import IN_DOCKER

###################### Config ##########################


class ShellConfig(BaseConfigSet):
    toml_section_header: str = "SHELL_CONFIG"

    DEBUG: bool = Field(default="--debug" in sys.argv)

    IS_TTY: bool = Field(default=sys.stdout.isatty())
    USE_COLOR: bool = Field(default=sys.stdout.isatty())
    SHOW_PROGRESS: bool = Field(default=sys.stdout.isatty())

    IN_DOCKER: bool = Field(default=IN_DOCKER)
    IN_QEMU: bool = Field(default=False)

    ANSI: Dict[str, str] = Field(
        default_factory=lambda: CONSTANTS.DEFAULT_CLI_COLORS if sys.stdout.isatty() else CONSTANTS.DISABLED_CLI_COLORS
    )

    @property
    def TERM_WIDTH(self) -> int:
        if not self.IS_TTY:
            return 200
        return shutil.get_terminal_size((140, 10)).columns

    @property
    def COMMIT_HASH(self) -> Optional[str]:
        return get_COMMIT_HASH()

    @property
    def BUILD_TIME(self) -> str:
        return get_BUILD_TIME()


SHELL_CONFIG = ShellConfig()


class StorageConfig(BaseConfigSet):
    toml_section_header: str = "STORAGE_CONFIG"

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


STORAGE_CONFIG = StorageConfig()


class GeneralConfig(BaseConfigSet):
    toml_section_header: str = "GENERAL_CONFIG"

    TAG_SEPARATOR_PATTERN: str = Field(default=r"[,]")


GENERAL_CONFIG = GeneralConfig()


class ServerConfig(BaseConfigSet):
    toml_section_header: str = "SERVER_CONFIG"

    SERVER_SECURITY_MODES: ClassVar[tuple[str, ...]] = (
        "safe-subdomains-fullreplay",
        "safe-onedomain-nojsreplay",
        "unsafe-onedomain-noadmin",
        "danger-onedomain-fullreplay",
    )

    SECRET_KEY: str = Field(default_factory=lambda: get_random_string(50, "abcdefghijklmnopqrstuvwxyz0123456789_"))
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
        default="Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests."
    )
    # CUSTOM_TEMPLATES_DIR: Path          = Field(default=None)  # this is now a constant

    PUBLIC_INDEX: bool = Field(default=True)
    PUBLIC_SNAPSHOTS: bool = Field(default=True)
    PUBLIC_ADD_VIEW: bool = Field(default=False)

    ADMIN_USERNAME: Optional[str] = Field(default=None)
    ADMIN_PASSWORD: Optional[str] = Field(default=None)

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


SERVER_CONFIG = ServerConfig()


def _print_server_security_mode_warning() -> None:
    if not SERVER_CONFIG.IS_LOWER_SECURITY_MODE:
        return

    print(
        f"[yellow][!] WARNING: ArchiveBox is running with SERVER_SECURITY_MODE={SERVER_CONFIG.SERVER_SECURITY_MODE}[/yellow]",
        file=sys.stderr,
    )
    print(
        "[yellow]    Archived pages may share an origin with privileged app routes in this mode.[/yellow]",
        file=sys.stderr,
    )
    print(
        "[yellow]    To switch to the safer isolated setup:[/yellow]",
        file=sys.stderr,
    )
    print(
        "[yellow]    1. Set SERVER_SECURITY_MODE=safe-subdomains-fullreplay[/yellow]",
        file=sys.stderr,
    )
    print(
        "[yellow]    2. Point *.archivebox.localhost (or your chosen base domain) at this server[/yellow]",
        file=sys.stderr,
    )
    print(
        "[yellow]    3. Configure wildcard DNS/TLS or your reverse proxy so admin., web., api., and snapshot subdomains resolve[/yellow]",
        file=sys.stderr,
    )


_print_server_security_mode_warning()


class ArchivingConfig(BaseConfigSet):
    toml_section_header: str = "ARCHIVING_CONFIG"

    ONLY_NEW: bool = Field(default=True)
    OVERWRITE: bool = Field(default=False)

    TIMEOUT: int = Field(default=60)
    MAX_URL_ATTEMPTS: int = Field(default=50)

    RESOLUTION: str = Field(default="1440,2000")
    CHECK_SSL_VALIDITY: bool = Field(default=True)
    USER_AGENT: str = Field(
        default=f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 ArchiveBox/{VERSION} (+https://github.com/ArchiveBox/ArchiveBox/)"
    )
    COOKIES_FILE: Path | None = Field(default=None)

    URL_DENYLIST: str = Field(default=r"\.(css|js|otf|ttf|woff|woff2|gstatic\.com|googleapis\.com/css)(\?.*)?$", alias="URL_BLACKLIST")
    URL_ALLOWLIST: str | None = Field(default=None, alias="URL_WHITELIST")

    SAVE_ALLOWLIST: Dict[str, List[str]] = Field(default={})  # mapping of regex patterns to list of archive methods
    SAVE_DENYLIST: Dict[str, List[str]] = Field(default={})

    DEFAULT_PERSONA: str = Field(default="Default")

    def warn_if_invalid(self) -> None:
        if int(self.TIMEOUT) < 5:
            print(f"[red][!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={self.TIMEOUT} seconds)[/red]", file=sys.stderr)
            print("    You must allow *at least* 5 seconds for indexing and archive methods to run succesfully.", file=sys.stderr)
            print("    (Setting it to somewhere between 30 and 3000 seconds is recommended)", file=sys.stderr)
            print(file=sys.stderr)
            print("    If you want to make ArchiveBox run faster, disable specific archive methods instead:", file=sys.stderr)
            print("        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#archive-method-toggles", file=sys.stderr)
            print(file=sys.stderr)

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
    def SAVE_ALLOWLIST_PTNS(self) -> Dict[re.Pattern, List[str]]:
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
    def SAVE_DENYLIST_PTNS(self) -> Dict[re.Pattern, List[str]]:
        return (
            {
                # regexp: methods list
                re.compile(key, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS): val
                for key, val in self.SAVE_DENYLIST.items()
            }
            if self.SAVE_DENYLIST
            else {}
        )


ARCHIVING_CONFIG = ArchivingConfig()
ARCHIVING_CONFIG.warn_if_invalid()


class SearchBackendConfig(BaseConfigSet):
    toml_section_header: str = "SEARCH_BACKEND_CONFIG"

    USE_INDEXING_BACKEND: bool = Field(default=True)
    USE_SEARCHING_BACKEND: bool = Field(default=True)

    SEARCH_BACKEND_ENGINE: str = Field(default="ripgrep")
    SEARCH_PROCESS_HTML: bool = Field(default=True)


SEARCH_BACKEND_CONFIG = SearchBackendConfig()
