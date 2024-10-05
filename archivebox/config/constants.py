__package__ = 'archivebox.config'


import os
import re
import platform
import tempfile

from typing import Dict
from pathlib import Path
import importlib.metadata
from collections.abc import Mapping

from benedict import benedict

from ..misc.logging import DEFAULT_CLI_COLORS

###################### Config ##########################

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent    # archivebox source code dir
DATA_DIR: Path = Path(os.getcwd()).resolve()                    # archivebox user data dir
ARCHIVE_DIR: Path = DATA_DIR / 'archive'                      # archivebox snapshot data dir

def _detect_installed_version(PACKAGE_DIR: Path):
    """Autodetect the installed archivebox version by using pip package metadata, pyproject.toml file, or package.json file"""
    try:
        # if in production install, use pip-installed package metadata
        return importlib.metadata.version(__package__ or 'archivebox').strip()
    except importlib.metadata.PackageNotFoundError:
        pass

    try:
        # if in dev Git repo dir, use pyproject.toml file
        pyproject_config = (PACKAGE_DIR.parent / 'pyproject.toml').read_text().split('\n')
        for line in pyproject_config:
            if line.startswith('version = '):
                return line.split(' = ', 1)[-1].strip('"').strip()
    except FileNotFoundError:
        # building docs, pyproject.toml is not available
        pass

    # raise Exception('Failed to detect installed archivebox version!')
    return 'dev'

VERSION: str = _detect_installed_version(PACKAGE_DIR)




class ConstantsDict(Mapping):
    IN_DOCKER = os.environ.get('IN_DOCKER', False) in ('1', 'true', 'True', 'yes')
    OS = platform.system().lower()      # darwin, linux, etc.
    ARCH = platform.machine().lower()   # arm64, x86_64, etc.
    LIB_DIR_SCOPE = f'{ARCH}-{OS}' + ('-docker' if IN_DOCKER else '')

    PACKAGE_DIR: Path = PACKAGE_DIR     # archivebox source code dir
    DATA_DIR: Path = DATA_DIR           # archivebox user data dir
    ARCHIVE_DIR: Path = ARCHIVE_DIR     # archivebox snapshot data dir
    VERSION: str = VERSION
    
    PACKAGE_DIR_NAME: str               = PACKAGE_DIR.name
    TEMPLATES_DIR_NAME: str             = 'templates'
    TEMPLATES_DIR: Path                 = PACKAGE_DIR / TEMPLATES_DIR_NAME
    STATIC_DIR: Path                    = TEMPLATES_DIR / 'static'
    USER_PLUGINS_DIR_NAME: str          = 'user_plugins'
    CUSTOM_TEMPLATES_DIR_NAME: str      = 'user_templates'

    ARCHIVE_DIR_NAME: str = 'archive'
    SOURCES_DIR_NAME: str = 'sources'
    PERSONAS_DIR_NAME: str = 'personas'
    CRONTABS_DIR_NAME: str = 'crontabs'
    CACHE_DIR_NAME: str = 'cache'
    LOGS_DIR_NAME: str = 'logs'
    LIB_DIR_NAME: str = 'lib'
    TMP_DIR_NAME: str = 'tmp'

    SYSTEM_TMP_DIR: Path                = Path(os.environ['SYSTEM_TMP_DIR']) if 'SYSTEM_TMP_DIR' in os.environ else (Path(tempfile.gettempdir()) / 'archivebox')
    # DATA_DIR_TMP_DIR: Path              = DATA_DIR / TMP_DIR_NAME / machineid.hashed_id('archivebox')[:16]   # cant be used because of socket path length restrictions break too often if data dir is in some deep subdir: ocket.error reported AF_UNIX path too long
    SYSTEM_LIB_DIR: Path                = Path(os.environ['SYSTEM_LIB_DIR']) if 'SYSTEM_LIB_DIR' in os.environ else (PACKAGE_DIR / LIB_DIR_NAME)
    DATA_DIR_LIB_DIR: Path              = DATA_DIR / LIB_DIR_NAME / LIB_DIR_SCOPE

    ARCHIVE_DIR: Path                   = DATA_DIR / ARCHIVE_DIR_NAME
    SOURCES_DIR: Path                   = DATA_DIR / SOURCES_DIR_NAME
    PERSONAS_DIR: Path                  = DATA_DIR / PERSONAS_DIR_NAME
    CACHE_DIR: Path                     = DATA_DIR / CACHE_DIR_NAME
    LOGS_DIR: Path                      = DATA_DIR / LOGS_DIR_NAME
    LIB_DIR: Path                       = SYSTEM_LIB_DIR if IN_DOCKER else DATA_DIR_LIB_DIR  # e.g. /app/lib or ./data/lib/arm64-darwin-docker
    TMP_DIR: Path                       = SYSTEM_TMP_DIR
    CUSTOM_TEMPLATES_DIR: Path          = DATA_DIR / CUSTOM_TEMPLATES_DIR_NAME
    USER_PLUGINS_DIR: Path              = DATA_DIR / USER_PLUGINS_DIR_NAME

    LIB_PIP_DIR: Path                   = LIB_DIR / 'pip'
    LIB_NPM_DIR: Path                   = LIB_DIR / 'npm'
    LIB_BROWSERS_DIR: Path              = LIB_DIR / 'browsers'
    LIB_BIN_DIR: Path                   = LIB_DIR / 'bin'
    BIN_DIR: Path                       = LIB_BIN_DIR

    CONFIG_FILENAME: str = 'ArchiveBox.conf'
    SQL_INDEX_FILENAME: str = 'index.sqlite3'
    QUEUE_DATABASE_FILENAME: str = 'queue.sqlite3'

    CONFIG_FILE: Path                   = DATA_DIR / CONFIG_FILENAME
    DATABASE_FILE: Path                 = DATA_DIR / SQL_INDEX_FILENAME
    QUEUE_DATABASE_FILE: Path           = DATA_DIR / QUEUE_DATABASE_FILENAME

    JSON_INDEX_FILENAME: str = 'index.json'
    HTML_INDEX_FILENAME: str = 'index.html'
    ROBOTS_TXT_FILENAME: str = 'robots.txt'
    FAVICON_FILENAME: str = 'favicon.ico'

    TIMEZONE: str                             = 'UTC'
    DEFAULT_CLI_COLORS: Dict[str, str]        = DEFAULT_CLI_COLORS
    DISABLED_CLI_COLORS: Dict[str, str]       = benedict({k: '' for k in DEFAULT_CLI_COLORS})

    ALLOWDENYLIST_REGEX_FLAGS: int = re.IGNORECASE | re.UNICODE | re.MULTILINE

    STATICFILE_EXTENSIONS: frozenset[str] = frozenset((
        # 99.999% of the time, URLs ending in these extensions are static files
        # that can be downloaded as-is, not html pages that need to be rendered
        'gif', 'jpeg', 'jpg', 'png', 'tif', 'tiff', 'wbmp', 'ico', 'jng', 'bmp',
        'svg', 'svgz', 'webp', 'ps', 'eps', 'ai',
        'mp3', 'mp4', 'm4a', 'mpeg', 'mpg', 'mkv', 'mov', 'webm', 'm4v',
        'flv', 'wmv', 'avi', 'ogg', 'ts', 'm3u8',
        'pdf', 'txt', 'rtf', 'rtfd', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx',
        'atom', 'rss', 'css', 'js', 'json',
        'dmg', 'iso', 'img',
        'rar', 'war', 'hqx', 'zip', 'gz', 'bz2', '7z',

        # Less common extensions to consider adding later
        # jar, swf, bin, com, exe, dll, deb
        # ear, hqx, eot, wmlc, kml, kmz, cco, jardiff, jnlp, run, msi, msp, msm,
        # pl pm, prc pdb, rar, rpm, sea, sit, tcl tk, der, pem, crt, xpi, xspf,
        # ra, mng, asx, asf, 3gpp, 3gp, mid, midi, kar, jad, wml, htc, mml

        # These are always treated as pages, not as static files, never add them:
        # html, htm, shtml, xhtml, xml, aspx, php, cgi
    ))

    INGORED_PATHS: frozenset[str] = frozenset((
        ".git",
        ".svn",
        ".DS_Store",
        ".gitignore",
        "lost+found",
        ".DS_Store",
        ".env",
        "Dockerfile",
        ".ArchiveBox.conf.bak",
    ))
    PIP_RELATED_NAMES: frozenset[str] = frozenset((
        ".venv",
        "venv",
        "virtualenv",
        ".virtualenv",
    ))
    NPM_RELATED_NAMES: frozenset[str] = frozenset((
        "node_modules",
        "package.json",
        "package-lock.json",
        "yarn.lock",
    ))

    DATA_DIR_NAMES: frozenset[str] = frozenset((
        ARCHIVE_DIR_NAME,
        SOURCES_DIR_NAME,
        LOGS_DIR_NAME,
        CACHE_DIR_NAME,
        LIB_DIR_NAME,
        TMP_DIR_NAME,
        PERSONAS_DIR_NAME,
        CUSTOM_TEMPLATES_DIR_NAME,
        USER_PLUGINS_DIR_NAME,
        CRONTABS_DIR_NAME,
    ))
    DATA_DIRS: frozenset[Path] = frozenset(DATA_DIR / dirname for dirname in DATA_DIR_NAMES)
    DATA_FILE_NAMES: frozenset[str] = frozenset((
        CONFIG_FILENAME,
        SQL_INDEX_FILENAME,
        f"{SQL_INDEX_FILENAME}-wal",
        f"{SQL_INDEX_FILENAME}-shm",
        QUEUE_DATABASE_FILENAME,
        f"{QUEUE_DATABASE_FILENAME}-wal",
        f"{QUEUE_DATABASE_FILENAME}-shm",
        "search.sqlite3",
        JSON_INDEX_FILENAME,
        HTML_INDEX_FILENAME,
        ROBOTS_TXT_FILENAME,
        FAVICON_FILENAME,
        CONFIG_FILENAME,
        f"{CONFIG_FILENAME}.bak",
        "static_index.json",
    ))

    # When initializing archivebox in a new directory, we check to make sure the dir is
    # actually empty so that we dont clobber someone's home directory or desktop by accident.
    # These files are exceptions to the is_empty check when we're trying to init a new dir,
    # as they could be from a previous archivebox version, system artifacts, dependencies, etc.
    ALLOWED_IN_DATA_DIR: frozenset[str] = frozenset((
        *INGORED_PATHS,
        *PIP_RELATED_NAMES,
        *NPM_RELATED_NAMES,
        *DATA_DIR_NAMES,
        *DATA_FILE_NAMES,
        "static",                # created by old static exports <v0.6.0
        "sonic",                 # created by docker bind mount
    ))

    CODE_LOCATIONS = benedict({
        'PACKAGE_DIR': {
            'path': (PACKAGE_DIR).resolve(),
            'enabled': True,
            'is_valid': (PACKAGE_DIR / '__main__.py').exists(),
        },
        'TEMPLATES_DIR': {
            'path': TEMPLATES_DIR.resolve(),
            'enabled': True,
            'is_valid': STATIC_DIR.exists(),
        },
        'LIB_DIR': {
            'path': LIB_DIR.resolve(),
            'enabled': True,
            'is_valid': LIB_DIR.is_dir(),
        },
        'TMP_DIR': {
            'path': TMP_DIR.resolve(),
            'enabled': True,
            'is_valid': TMP_DIR.is_dir(),
        },
    })
        
    DATA_LOCATIONS = benedict({
        "DATA_DIR": {
            "path": DATA_DIR.resolve(),
            "enabled": True,
            "is_valid": DATABASE_FILE.exists(),
            "is_mount": os.path.ismount(DATA_DIR.resolve()),
        },
        "CONFIG_FILE": {
            "path": CONFIG_FILE.resolve(),
            "enabled": True,
            "is_valid": CONFIG_FILE.exists(),
        },
        "SQL_INDEX": {
            "path": DATABASE_FILE.resolve(),
            "enabled": True,
            "is_valid": DATABASE_FILE.exists(),
            "is_mount": os.path.ismount(DATABASE_FILE.resolve()),
        },
        "QUEUE_DATABASE": {
            "path": QUEUE_DATABASE_FILE.resolve(),
            "enabled": True,
            "is_valid": QUEUE_DATABASE_FILE.exists(),
            "is_mount": os.path.ismount(QUEUE_DATABASE_FILE.resolve()),
        },
        "ARCHIVE_DIR": {
            "path": ARCHIVE_DIR.resolve(),
            "enabled": True,
            "is_valid": ARCHIVE_DIR.exists(),
            "is_mount": os.path.ismount(ARCHIVE_DIR.resolve()),
        },
        "SOURCES_DIR": {
            "path": SOURCES_DIR.resolve(),
            "enabled": True,
            "is_valid": SOURCES_DIR.exists(),
        },
        "LOGS_DIR": {
            "path": LOGS_DIR.resolve(),
            "enabled": True,
            "is_valid": LOGS_DIR.is_dir(),
        },
        # "CACHE_DIR": {
        #     "path": CACHE_DIR.resolve(),
        #     "enabled": True,
        #     "is_valid": CACHE_DIR.is_dir(),
        # },
        "PERSONAS_DIR": {
            "path": PERSONAS_DIR.resolve(),
            "enabled": PERSONAS_DIR.exists(),
            "is_valid": PERSONAS_DIR.is_dir(),
        },
        'CUSTOM_TEMPLATES_DIR': {
            'path': CUSTOM_TEMPLATES_DIR.resolve(),
            'enabled': CUSTOM_TEMPLATES_DIR.exists(),
            'is_valid': CUSTOM_TEMPLATES_DIR.is_dir(),
        },
        'USER_PLUGINS_DIR': {
            'path': USER_PLUGINS_DIR.resolve(),
            'enabled': USER_PLUGINS_DIR.exists(),
            'is_valid': USER_PLUGINS_DIR.is_dir(),
        },
    })

    @classmethod
    def __getitem__(cls, key: str):
        return getattr(cls, key)
    
    @classmethod
    def __benedict__(cls):
        return benedict({key: value for key, value in cls.__dict__.items() if key.isupper() and not key.startswith('_')})
    
    @classmethod
    def __len__(cls):
        return len(cls.__benedict__())

    @classmethod
    def __iter__(cls):
        return iter(cls.__benedict__())

CONSTANTS = ConstantsDict()
CONSTANTS_CONFIG = CONSTANTS.__benedict__()

# add all key: values to globals() for easier importing
globals().update(CONSTANTS)


# these need to always exist as we need them to run almost everything
CONSTANTS.LIB_DIR.mkdir(parents=True, exist_ok=True)
CONSTANTS.TMP_DIR.mkdir(parents=True, exist_ok=True)
