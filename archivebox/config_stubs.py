from pathlib import Path
from typing import Optional, Dict, Union, Tuple, Callable, Pattern, Type, Any, List
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

    PACKAGE_DIR: Path
    OUTPUT_DIR: Path
    CONFIG_FILE: Path
    ONLY_NEW: bool
    TIMEOUT: int
    MEDIA_TIMEOUT: int
    OUTPUT_PERMISSIONS: str
    RESTRICT_FILE_NAMES: str
    URL_BLACKLIST: str

    SECRET_KEY: Optional[str]
    BIND_ADDR: str
    ALLOWED_HOSTS: str
    DEBUG: bool
    PUBLIC_INDEX: bool
    PUBLIC_SNAPSHOTS: bool
    FOOTER_INFO: str

    SAVE_TITLE: bool
    SAVE_FAVICON: bool
    SAVE_WGET: bool
    SAVE_WGET_REQUISITES: bool
    SAVE_SINGLEFILE: bool
    SAVE_READABILITY: bool
    SAVE_MERCURY: bool
    SAVE_PDF: bool
    SAVE_SCREENSHOT: bool
    SAVE_DOM: bool
    SAVE_WARC: bool
    SAVE_GIT: bool
    SAVE_MEDIA: bool
    SAVE_ARCHIVE_DOT_ORG: bool

    RESOLUTION: str
    GIT_DOMAINS: str
    CHECK_SSL_VALIDITY: bool
    CURL_USER_AGENT: str
    WGET_USER_AGENT: str
    CHROME_USER_AGENT: str
    COOKIES_FILE: Union[str, Path, None]
    CHROME_USER_DATA_DIR: Union[str, Path, None]
    CHROME_HEADLESS: bool
    CHROME_SANDBOX: bool

    USE_CURL: bool
    USE_WGET: bool
    USE_SINGLEFILE: bool
    USE_READABILITY: bool
    USE_MERCURY: bool
    USE_GIT: bool
    USE_CHROME: bool
    USE_YOUTUBEDL: bool
    CURL_BINARY: str
    GIT_BINARY: str
    WGET_BINARY: str
    SINGLEFILE_BINARY: str
    READABILITY_BINARY: str
    MERCURY_BINARY: str
    YOUTUBEDL_BINARY: str
    CHROME_BINARY: Optional[str]

    YOUTUBEDL_ARGS: List[str]
    WGET_ARGS: List[str]
    CURL_ARGS: List[str]
    GIT_ARGS: List[str]


ConfigDefaultValueGetter = Callable[[ConfigDict], ConfigValue]
ConfigDefaultValue = Union[ConfigValue, ConfigDefaultValueGetter]

ConfigDefault = TypedDict('ConfigDefault', {
    'default': ConfigDefaultValue,
    'type': Optional[Type],
    'aliases': Optional[Tuple[str, ...]],
}, total=False)

ConfigDefaultDict = Dict[str, ConfigDefault]
