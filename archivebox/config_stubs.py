from pathlib import Path
from typing import Optional, Dict, Union, Tuple, Callable, Pattern, Type, Any, List
from mypy_extensions import TypedDict



SimpleConfigValue = Union[str, bool, int, None, Pattern, Dict[str, Any]]
SimpleConfigValueDict = Dict[str, SimpleConfigValue]
SimpleConfigValueGetter = Callable[[], SimpleConfigValue]
ConfigValue = Union[SimpleConfigValue, SimpleConfigValueDict, SimpleConfigValueGetter]

SHArgs = List[str]   # shell command args list e.g. ["--something=1", "--someotherarg"]


class BaseConfig(TypedDict):
    pass

class ConfigDict(BaseConfig, total=False):
    """
    # Regenerate by pasting this quine into `archivebox shell` 🥚
    from archivebox.config import ConfigDict, CONFIG_SCHEMA
    print('class ConfigDict(BaseConfig, total=False):')
    print('    ' + '"'*3 + ConfigDict.__doc__ + '"'*3)
    for section, configs in CONFIG_SCHEMA.items():
        for key, attrs in configs.items():
            Type, default = attrs['type'], attrs['default']
            if default is None:
                print(f'    {key}: Optional[{Type.__name__}]')
            else:
                print(f'    {key}: {Type.__name__}')
        print()
    """
    IS_TTY: bool
    USE_COLOR: bool
    SHOW_PROGRESS: bool
    IN_DOCKER: bool
    IN_QEMU: bool
    PUID: int
    PGID: int

    OUTPUT_DIR: Optional[str]
    CONFIG_FILE: Optional[str]
    ONLY_NEW: bool
    TIMEOUT: int
    MEDIA_TIMEOUT: int
    OUTPUT_PERMISSIONS: str
    RESTRICT_FILE_NAMES: str
    URL_DENYLIST: str
    URL_ALLOWLIST: Optional[str]
    ADMIN_USERNAME: Optional[str]
    ADMIN_PASSWORD: Optional[str]
    ENFORCE_ATOMIC_WRITES: bool
    TAG_SEPARATOR_PATTERN: str

    SECRET_KEY: Optional[str]
    BIND_ADDR: str
    ALLOWED_HOSTS: str
    DEBUG: bool
    PUBLIC_INDEX: bool
    PUBLIC_SNAPSHOTS: bool
    PUBLIC_ADD_VIEW: bool
    FOOTER_INFO: str
    SNAPSHOTS_PER_PAGE: int
    CUSTOM_TEMPLATES_DIR: Optional[str]
    TIME_ZONE: str
    TIMEZONE: str
    REVERSE_PROXY_USER_HEADER: str
    REVERSE_PROXY_WHITELIST: str
    LOGOUT_REDIRECT_URL: str
    PREVIEW_ORIGINALS: bool
    LDAP: bool
    LDAP_SERVER_URI: Optional[str]
    LDAP_BIND_DN: Optional[str]
    LDAP_BIND_PASSWORD: Optional[str]
    LDAP_USER_BASE: Optional[str]
    LDAP_USER_FILTER: Optional[str]
    LDAP_USERNAME_ATTR: Optional[str]
    LDAP_FIRSTNAME_ATTR: Optional[str]
    LDAP_LASTNAME_ATTR: Optional[str]
    LDAP_EMAIL_ATTR: Optional[str]
    LDAP_CREATE_SUPERUSER: bool

    SAVE_TITLE: bool
    SAVE_FAVICON: bool
    SAVE_WGET: bool
    SAVE_WGET_REQUISITES: bool
    SAVE_SINGLEFILE: bool
    SAVE_READABILITY: bool
    SAVE_MERCURY: bool
    SAVE_HTMLTOTEXT: bool
    SAVE_PDF: bool
    SAVE_SCREENSHOT: bool
    SAVE_DOM: bool
    SAVE_HEADERS: bool
    SAVE_WARC: bool
    SAVE_GIT: bool
    SAVE_MEDIA: bool
    SAVE_ARCHIVE_DOT_ORG: bool
    SAVE_ALLOWLIST: dict
    SAVE_DENYLIST: dict

    RESOLUTION: str
    GIT_DOMAINS: str
    CHECK_SSL_VALIDITY: bool
    MEDIA_MAX_SIZE: str
    CURL_USER_AGENT: str
    WGET_USER_AGENT: str
    CHROME_USER_AGENT: str
    COOKIES_FILE: Optional[str]
    CHROME_USER_DATA_DIR: Optional[str]
    CHROME_TIMEOUT: int
    CHROME_HEADLESS: bool
    CHROME_SANDBOX: bool
    YOUTUBEDL_ARGS: list
    WGET_ARGS: list
    CURL_ARGS: list
    GIT_ARGS: list
    SINGLEFILE_ARGS: Optional[list]
    FAVICON_PROVIDER: str

    USE_INDEXING_BACKEND: bool
    USE_SEARCHING_BACKEND: bool
    SEARCH_BACKEND_ENGINE: str
    SEARCH_BACKEND_HOST_NAME: str
    SEARCH_BACKEND_PORT: int
    SEARCH_BACKEND_PASSWORD: str
    SEARCH_PROCESS_HTML: bool
    SONIC_COLLECTION: str
    SONIC_BUCKET: str
    SEARCH_BACKEND_TIMEOUT: int
    FTS_SEPARATE_DATABASE: bool
    FTS_TOKENIZERS: str
    FTS_SQLITE_MAX_LENGTH: int

    USE_CURL: bool
    USE_WGET: bool
    USE_SINGLEFILE: bool
    USE_READABILITY: bool
    USE_MERCURY: bool
    USE_GIT: bool
    USE_CHROME: bool
    USE_NODE: bool
    USE_YOUTUBEDL: bool
    USE_RIPGREP: bool
    CURL_BINARY: str
    GIT_BINARY: str
    WGET_BINARY: str
    SINGLEFILE_BINARY: str
    READABILITY_BINARY: str
    MERCURY_BINARY: str
    YOUTUBEDL_BINARY: str
    NODE_BINARY: str
    RIPGREP_BINARY: str
    CHROME_BINARY: Optional[str]
    POCKET_CONSUMER_KEY: Optional[str]
    POCKET_ACCESS_TOKENS: dict
    READWISE_READER_TOKENS: dict


ConfigDefaultValueGetter = Callable[[ConfigDict], ConfigValue]
ConfigDefaultValue = Union[ConfigValue, ConfigDefaultValueGetter]

ConfigDefault = TypedDict('ConfigDefault', {
    'default': ConfigDefaultValue,
    'type': Optional[Type],
    'aliases': Optional[Tuple[str, ...]],
}, total=False)

ConfigDefaultDict = Dict[str, ConfigDefault]
