from typing import Optional, Dict, Union, Tuple, Callable, Pattern, Type, Any
from mypy_extensions import TypedDict


SimpleConfigValue = Union[str, bool, int, None, Pattern, Dict[str, Any]]
SimpleConfigValueDict = Dict[str, SimpleConfigValue]
SimpleConfigValueGetter = Callable[[], SimpleConfigValue]
ConfigValue = Union[SimpleConfigValue, SimpleConfigValueDict, SimpleConfigValueGetter]


class BaseConfig(TypedDict):
    pass

class ConfigDict(BaseConfig, total=False):
    """
    # Regenerate by pasting this quine into `archivebox shell` 🥚
    from archivebox.config import ConfigDict, CONFIG_DEFAULTS
    print('class ConfigDict(BaseConfig, total=False):')
    print('    ' + '"'*3 + ConfigDict.__doc__ + '"'*3)
    for section, configs in CONFIG_DEFAULTS.items():
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

    OUTPUT_DIR: str
    CONFIG_FILE: str
    ONLY_NEW: bool
    TIMEOUT: int
    MEDIA_TIMEOUT: int
    OUTPUT_PERMISSIONS: str
    URL_BLACKLIST: Optional[str]

    SECRET_KEY: str
    ALLOWED_HOSTS: str
    DEBUG: bool
    PUBLIC_INDEX: bool
    PUBLIC_SNAPSHOTS: bool
    FOOTER_INFO: str
    ACTIVE_THEME: str

    SAVE_TITLE: bool
    SAVE_FAVICON: bool
    SAVE_WGET: bool
    SAVE_WGET_REQUISITES: bool
    SAVE_PDF: bool
    SAVE_SCREENSHOT: bool
    SAVE_DOM: bool
    SAVE_SINGLEFILE: bool
    SAVE_WARC: bool
    SAVE_GIT: bool
    SAVE_MEDIA: bool
    SAVE_PLAYLISTS: bool
    SAVE_ARCHIVE_DOT_ORG: bool

    RESOLUTION: str
    GIT_DOMAINS: str
    CHECK_SSL_VALIDITY: bool
    CURL_USER_AGENT: str
    WGET_USER_AGENT: str
    CHROME_USER_AGENT: str
    COOKIES_FILE: Optional[str]
    CHROME_USER_DATA_DIR: Optional[str]
    CHROME_HEADLESS: bool
    CHROME_SANDBOX: bool

    USE_CURL: bool
    USE_WGET: bool
    USE_GIT: bool
    USE_CHROME: bool
    USE_YOUTUBEDL: bool
    USE_SINGLEFILE: bool

    CURL_BINARY: Optional[str]
    GIT_BINARY: Optional[str]
    WGET_BINARY: Optional[str]
    YOUTUBEDL_BINARY: Optional[str]
    CHROME_BINARY: Optional[str]
    SINGLEFILE_BINARY: Optional[str]

    TERM_WIDTH: Callable[[], int]
    USER: str
    ANSI: Dict[str, str]
    REPO_DIR: str
    PYTHON_DIR: str
    TEMPLATES_DIR: str
    ARCHIVE_DIR: str
    SOURCES_DIR: str
    LOGS_DIR: str

    URL_BLACKLIST_PTN: Optional[Pattern]
    WGET_AUTO_COMPRESSION: bool

    ARCHIVEBOX_BINARY: str
    VERSION: str
    GIT_SHA: str

    PYTHON_BINARY: str
    PYTHON_ENCODING: str
    PYTHON_VERSION: str

    DJANGO_BINARY: str
    DJANGO_VERSION: str

    CURL_VERSION: str
    WGET_VERSION: str
    YOUTUBEDL_VERSION: str
    GIT_VERSION: str
    CHROME_VERSION: str

    DEPENDENCIES: Dict[str, SimpleConfigValueDict]
    CODE_LOCATIONS: Dict[str, SimpleConfigValueDict]
    CONFIG_LOCATIONS: Dict[str, SimpleConfigValueDict]
    DATA_LOCATIONS: Dict[str, SimpleConfigValueDict]
    CHROME_OPTIONS: Dict[str, SimpleConfigValue]


ConfigDefaultValueGetter = Callable[[ConfigDict], ConfigValue]
ConfigDefaultValue = Union[ConfigValue, ConfigDefaultValueGetter]

ConfigDefault = TypedDict('ConfigDefault', {
    'default': ConfigDefaultValue,
    'type': Optional[Type],
    'aliases': Optional[Tuple[str, ...]],
}, total=False)

ConfigDefaultDict = Dict[str, ConfigDefault]
