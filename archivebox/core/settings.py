__package__ = 'archivebox.core'

import os
import re
import sys
import json
import platform
import shutil
import getpass
from typing import Optional
from pathlib import Path
from subprocess import run, PIPE, DEVNULL
from collections import defaultdict

import django
from django.utils.crypto import get_random_string

import environ

# from ..config import (                                                          # noqa: F401
#     DEBUG,
#     SECRET_KEY,
#     ALLOWED_HOSTS,
#     PYTHON_DIR,
#     ACTIVE_THEME,
#     SQL_INDEX_FILENAME,
#     OUTPUT_DIR,
# )
IS_SHELL = 'shell' in sys.argv[:3] or 'shell_plus' in sys.argv[:3]


########################## Config migration ################

def find_chrome_data_dir() -> Optional[str]:
    """find any installed chrome user data directories in the default locations"""
    # Precedence: Chromium, Chrome, Beta, Canary, Unstable, Dev
    # make sure data dir finding precedence order always matches binary finding order
    default_profile_paths = (
        '~/.config/chromium',
        '~/Library/Application Support/Chromium',
        '~/AppData/Local/Chromium/User Data',
        '~/.config/chrome',
        '~/.config/google-chrome',
        '~/Library/Application Support/Google/Chrome',
        '~/AppData/Local/Google/Chrome/User Data',
        '~/.config/google-chrome-stable',
        '~/.config/google-chrome-beta',
        '~/Library/Application Support/Google/Chrome Canary',
        '~/AppData/Local/Google/Chrome SxS/User Data',
        '~/.config/google-chrome-unstable',
        '~/.config/google-chrome-dev',
    )
    for path in default_profile_paths:
        full_path = Path(path).resolve()
        if full_path.exists():
            return full_path
    return None

def wget_supports_compression(wget_binary):
    cmd = [
        wget_binary,
        "--compression=auto",
        "--help",
    ]
    return not run(cmd, stdout=DEVNULL, stderr=DEVNULL).returncode

def bin_version(binary: Optional[str]) -> Optional[str]:
    """check the presence and return valid version line of a specified binary"""

    abspath = bin_path(binary)
    if not binary or not abspath:
        return None

    try:
        version_str = run([abspath, "--version"], stdout=PIPE).stdout.strip().decode()
        # take first 3 columns of first line of version info
        return ' '.join(version_str.split('\n')[0].strip().split()[:3])
    except OSError:
        pass
        # stderr(f'[X] Unable to find working version of dependency: {binary}', color='red')
        # stderr('    Make sure it\'s installed, then confirm it\'s working by running:')
        # stderr(f'        {binary} --version')
        # stderr()
        # stderr('    If you don\'t want to install it, you can disable it via config. See here for more info:')
        # stderr('        https://github.com/pirate/ArchiveBox/wiki/Install')
    return None

def bin_path(binary: Optional[str]) -> Optional[str]:
    if binary is None:
        return None

    node_modules_bin = Path('.') / 'node_modules' / '.bin' / binary
    if node_modules_bin.exists():
        return str(node_modules_bin.resolve())

    return shutil.which(os.path.expanduser(binary)) or binary

def find_chrome_binary() -> Optional[str]:
    """find any installed chrome binaries in the default locations"""
    # Precedence: Chromium, Chrome, Beta, Canary, Unstable, Dev
    # make sure data dir finding precedence order always matches binary finding order
    default_executable_paths = (
        'chromium-browser',
        'chromium',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        'chrome',
        'google-chrome',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        'google-chrome-stable',
        'google-chrome-beta',
        'google-chrome-canary',
        '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
        'google-chrome-unstable',
        'google-chrome-dev',
    )
    for name in default_executable_paths:
        full_path_exists = shutil.which(name)
        if full_path_exists:
            return name
    
    return None

# Constants

DEFAULT_CLI_COLORS = {
    'reset': '\033[00;00m',
    'lightblue': '\033[01;30m',
    'lightyellow': '\033[01;33m',
    'lightred': '\033[01;35m',
    'red': '\033[01;31m',
    'green': '\033[01;32m',
    'blue': '\033[01;34m',
    'white': '\033[01;37m',
    'black': '\033[01;30m',
}
ANSI = {k: '' for k in DEFAULT_CLI_COLORS.keys()}

COLOR_DICT = defaultdict(lambda: [(0, 0, 0), (0, 0, 0)], {
    '00': [(0, 0, 0), (0, 0, 0)],
    '30': [(0, 0, 0), (0, 0, 0)],
    '31': [(255, 0, 0), (128, 0, 0)],
    '32': [(0, 200, 0), (0, 128, 0)],
    '33': [(255, 255, 0), (128, 128, 0)],
    '34': [(0, 0, 255), (0, 0, 128)],
    '35': [(255, 0, 255), (128, 0, 128)],
    '36': [(0, 255, 255), (0, 128, 128)],
    '37': [(255, 255, 255), (255, 255, 255)],
})

STATICFILE_EXTENSIONS = {
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
}



PYTHON_DIR_NAME = 'archivebox'
TEMPLATES_DIR_NAME = 'themes'

ARCHIVE_DIR_NAME = 'archive'
SOURCES_DIR_NAME = 'sources'
LOGS_DIR_NAME = 'logs'
STATIC_DIR_NAME = 'static'
SQL_INDEX_FILENAME = 'index.sqlite3'
JSON_INDEX_FILENAME = 'index.json'
HTML_INDEX_FILENAME = 'index.html'
ROBOTS_TXT_FILENAME = 'robots.txt'
FAVICON_FILENAME = 'favicon.ico'
CONFIG_FILENAME = 'ArchiveBox.conf'

# Some values needed to compute other values, so we load them first 
IS_TTY = sys.stdout.isatty()
IN_DOCKER= os.getenv("IN_DOCKER", False)

env = environ.Env(
    USE_COLOR=(bool, IS_TTY),
    SHOW_PROGRESS=(bool, False if platform.system() == 'Darwin' else IS_TTY),  # TODO: remove this temporary hack once progress bars are fixed on macOS
    
    OUTPUT_DIR=(str, None),
    CONFIG_FILE=(str, None),
    ONLY_NEW=(bool, True),
    TIMEOUT=(int, 60),
    MEDIA_TIMEOUT=(int, 3600),
    OUTPUT_PERMISSIONS=(str, '755'),
    RESTRICT_FILE_NAMES=(str, 'windows'),
    URL_BLACKLIST=(str, r'\.(css|js|otf|ttf|woff|woff2|gstatic\.com|googleapis\.com/css)(\?.*)?$'),  # to avoid downloading code assets as their own pages
    

    SECRET_KEY=(str, get_random_string(50, 'abcdefghijklmnopqrstuvwxyz0123456789-_+!.')),
    BIND_ADDR=(str, ['127.0.0.1:8000', '0.0.0.0:8000'][IN_DOCKER]),
    ALLOWED_HOSTS=(str, "*"),
    PUBLIC_INDEX=(bool, True),
    PUBLIC_SNAPSHOTS=(bool, True),
    PUBLIC_ADD_VIEW=(bool, False),
    DEBUG=(bool, True),
    FOOTER_INFO=(str, 'Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.'),
    ACTIVE_THEME=(str, 'default'),


    SAVE_TITLE=(bool, True),
    SAVE_FAVICON=(bool, True),
    SAVE_WGET=(bool, True),
    SAVE_WGET_REQUISITES=(bool, True),
    SAVE_SINGLEFILE=(bool, True),
    SAVE_READABILITY=(bool, True),
    SAVE_PDF=(bool, True),
    SAVE_SCREENSHOT=(bool, True),
    SAVE_DOM=(bool, True),
    SAVE_WARC=(bool, True), 
    SAVE_GIT=(bool, True),
    SAVE_MEDIA=(bool, True),
    SAVE_PLAYLISTS=(bool, True),
    SAVE_ARCHIVE_DOT_ORG=(bool, True),

    RESOLUTION=(str,  '1440,2000'),
    GIT_DOMAINS=(str,  'github.com,bitbucket.org,gitlab.com'),
    CHECK_SSL_VALIDITY=(bool, True),
    CURL_USER_AGENT=     (str,  'ArchiveBox/{VERSION} (+https://github.com/pirate/ArchiveBox/) curl/{CURL_VERSION}'),
    WGET_USER_AGENT=     (str,  'ArchiveBox/{VERSION} (+https://github.com/pirate/ArchiveBox/) wget/{WGET_VERSION}'),
    CHROME_USER_AGENT=   (str,  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36'),
    COOKIES_FILE=        (str,  None),
    CHROME_USER_DATA_DIR=(str,  None),
    CHROME_HEADLESS=     (bool, True),
    CHROME_SANDBOX=      (bool, not IN_DOCKER),

    USE_CURL=(bool, True),
    USE_WGET=(bool, True),
    USE_SINGLEFILE=(bool, True),
    USE_READABILITY=   (bool, True),
    USE_GIT=           (bool, True),
    USE_CHROME=        (bool, True),
    USE_NODE=          (bool, True),
    USE_YOUTUBEDL=     (bool, True),
    CURL_BINARY=       (str,  'curl'),
    GIT_BINARY=        (str,  'git'),
    WGET_BINARY=       (str,  'wget'),
    SINGLEFILE_BINARY= (str,  'single-file'),
    READABILITY_BINARY=(str,  'readability-extractor'),
    YOUTUBEDL_BINARY=  (str,  'youtube-dl'),
    CHROME_BINARY=     (str,  None)

)

environ.Env.read_env()

USE_COLOR = env("USE_COLOR")
SHOW_PROGRESS = env("SHOW_PROGRESS")

OUTPUT_DIR = env("OUTPUT_DIR")
CONFIG_FILE = env("CONFIG_FILE")
ONLY_NEW = env("ONLY_NEW")
TIMEOUT = env("TIMEOUT")
MEDIA_TIMEOUT = env("MEDIA_TIMEOUT")
OUTPUT_PERMISSIONS = env("OUTPUT_PERMISSIONS")
RESTRICT_FILE_NAMES = env("RESTRICT_FILE_NAMES")
URL_BLACKLIST = env("URL_BLACKLIST")


SECRET_KEY = env("SECRET_KEY")
BIND_ADDR = env("BIND_ADDR")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
PUBLIC_INDEX = env("PUBLIC_INDEX")
PUBLIC_SNAPSHOTS = env("PUBLIC_SNAPSHOTS")
PUBLIC_ADD_VIEW = env("PUBLIC_ADD_VIEW")
DEBUG = env("DEBUG")
FOOTER_INFO = env("FOOTER_INFO")
ACTIVE_THEME = env("ACTIVE_THEME")

SAVE_TITLE = env("SAVE_TITLE")
SAVE_FAVICON = env("SAVE_FAVICON")
SAVE_WGET = env("SAVE_WGET")
SAVE_WGET_REQUISITES = env("SAVE_WGET_REQUISITES")
SAVE_SINGLEFILE = env("SAVE_SINGLEFILE")
SAVE_READABILITY = env("SAVE_READABILITY")
SAVE_PDF = env("SAVE_PDF")
SAVE_SCREENSHOT = env("SAVE_SCREENSHOT")
SAVE_DOM = env("SAVE_DOM")
SAVE_WARC = env("SAVE_WARC")
SAVE_GIT = env("SAVE_GIT")
SAVE_MEDIA = env("SAVE_MEDIA")
SAVE_PLAYLISTS = env("SAVE_PLAYLISTS")
SAVE_ARCHIVE_DOT_ORG = env("SAVE_ARCHIVE_DOT_ORG")

RESOLUTION = env("RESOLUTION")
GIT_DOMAINS = env("GIT_DOMAINS")
CHECK_SSL_VALIDITY = env("CHECK_SSL_VALIDITY")
CURL_USER_AGENT = env("CURL_USER_AGENT")
WGET_USER_AGENT = env("WGET_USER_AGENT")
CHROME_USER_AGENT = env("CHROME_USER_AGENT")
COOKIES_FILE = env("COOKIES_FILE")
CHROME_USER_DATA_DIR = env("CHROME_USER_DATA_DIR")
CHROME_HEADLESS = env("CHROME_HEADLESS")
CHROME_SANDBOX = env("CHROME_SANDBOX")

USE_CURL = env("USE_CURL")
USE_WGET = env("USE_WGET")
USE_SINGLEFILE = env("USE_SINGLEFILE")
USE_READABILITY = env("USE_READABILITY")
USE_GIT = env("USE_GIT")
USE_CHROME = env("USE_CHROME")
USE_NODE = env("USE_NODE")
USE_YOUTUBEDL = env("USE_YOUTUBEDL")
CURL_BINARY = env("CURL_BINARY")
GIT_BINARY = env("GIT_BINARY")
WGET_BINARY = env("WGET_BINARY")
SINGLEFILE_BINARY = env("SINGLEFILE_BINARY")
READABILITY_BINARY = env("READABILITY_BINARY")
YOUTUBEDL_BINARY = env("YOUTUBEDL_BINARY")
CHROME_BINARY = env("CHROME_BINARY")


TERM_WIDTH = shutil.get_terminal_size((100, 10)).columns
USER= getpass.getuser() or os.getlogin()
ANSI= DEFAULT_CLI_COLORS if USE_COLOR else {k: '' for k in DEFAULT_CLI_COLORS.keys()}

REPO_DIR = Path(__file__).resolve().parent.parent.parent
PYTHON_DIR= REPO_DIR / PYTHON_DIR_NAME
TEMPLATES_DIR = PYTHON_DIR / TEMPLATES_DIR_NAME / 'legacy'

OUTPUT_DIR = Path(OUTPUT_DIR).resolve() if OUTPUT_DIR else Path(os.curdir).resolve()
ARCHIVE_DIR = OUTPUT_DIR / ARCHIVE_DIR_NAME
SOURCES_DIR= OUTPUT_DIR / SOURCES_DIR_NAME
LOGS_DIR= OUTPUT_DIR / LOGS_DIR_NAME 
CONFIG_FILE= Path(CONFIG_FILE).resolve() if CONFIG_FILE else OUTPUT_DIR / CONFIG_FILENAME
COOKIES_FILE= COOKIES_FILE and COOKIES_FILE.resolve()
CHROME_USER_DATA_DIR = find_chrome_data_dir() if CHROME_USER_DATA_DIR is None else (Path(CHROME_USER_DATA_DIR).resolve() if c['CHROME_USER_DATA_DIR'] else None)
URL_BLACKLIST_PTN=   URL_BLACKLIST and re.compile(URL_BLACKLIST or '', re.IGNORECASE | re.UNICODE | re.MULTILINE)

ARCHIVEBOX_BINARY=sys.argv[0]
VERSION=         json.loads((Path(PYTHON_DIR) / 'package.json').read_text().strip())['version']
GIT_SHA=         VERSION.split('+')[-1] or 'unknown'
PYTHON_BINARY=   sys.executable
PYTHON_ENCODING= sys.stdout.encoding.upper()
PYTHON_VERSION=  '{}.{}.{}'.format(*sys.version_info[:3])
DJANGO_BINARY=   django.__file__.replace('__init__.py', 'bin/django-admin.py')
DJANGO_VERSION=  '{}.{}.{} {} ({})'.format(*django.VERSION)

USE_CURL                 = USE_CURL and (SAVE_FAVICON or SAVE_TITLE or SAVE_ARCHIVE_DOT_ORG)
CURL_VERSION             = bin_version(CURL_BINARY) if USE_CURL else None
CURL_USER_AGENT          = CURL_USER_AGENT # TODO: deal with .format(**c)
SAVE_FAVICON             = USE_CURL and SAVE_FAVICON
SAVE_ARCHIVE_DOT_ORG     = USE_CURL and SAVE_ARCHIVE_DOT_ORG
USE_WGET                 = USE_WGET and SAVE_WGET or SAVE_WARC
WGET_VERSION             = bin_version(WGET_BINARY) if USE_WGET else None
WGET_AUTO_COMPRESSION    = wget_supports_compression(WGET_BINARY) if USE_WGET else False
WGET_USER_AGENT          = WGET_USER_AGENT # TODO: deal with .format(**c)
SAVE_WGET                = USE_WGET and SAVE_WGET
SAVE_WARC                = USE_WGET and SAVE_WARC

USE_SINGLEFILE=        USE_SINGLEFILE and SAVE_SINGLEFILE
SINGLEFILE_VERSION=    bin_version(SINGLEFILE_BINARY) if USE_SINGLEFILE else None
USE_READABILITY=       USE_READABILITY and SAVE_READABILITY
READABILITY_VERSION=   bin_version(READABILITY_BINARY) if USE_READABILITY else None
USE_GIT=               USE_GIT and SAVE_GIT
GIT_VERSION=           bin_version(GIT_BINARY) if USE_GIT else None
SAVE_GIT=              USE_GIT and SAVE_GIT
USE_YOUTUBEDL=         USE_YOUTUBEDL and SAVE_MEDIA
YOUTUBEDL_VERSION=     bin_version(YOUTUBEDL_BINARY) if USE_YOUTUBEDL else None
SAVE_MEDIA=            USE_YOUTUBEDL and SAVE_MEDIA
SAVE_PLAYLISTS=        SAVE_PLAYLISTS and SAVE_MEDIA
USE_CHROME=            USE_CHROME and (SAVE_PDF or SAVE_SCREENSHOT or SAVE_DOM or SAVE_SINGLEFILE)
CHROME_BINARY=         CHROME_BINARY if CHROME_BINARY else find_chrome_binary()
CHROME_VERSION=        bin_version(CHROME_BINARY) if USE_CHROME else None
USE_NODE=              USE_NODE and (SAVE_READABILITY or SAVE_SINGLEFILE)
SAVE_PDF=              USE_CHROME and SAVE_PDF
SAVE_SCREENSHOT=       USE_CHROME and SAVE_SCREENSHOT
SAVE_DOM=              USE_CHROME and SAVE_DOM
SAVE_SINGLEFILE=       USE_CHROME and USE_SINGLEFILE and USE_NODE
SAVE_READABILITY=      USE_READABILITY and USE_NODE
# DEPENDENCIES=          get_dependency_info(c)
# CODE_LOCATIONS=        get_code_locations(c)
# EXTERNAL_LOCATIONS=    get_external_locations(c)
# DATA_LOCATIONS=        get_data_locations(c)
# CHROME_OPTIONS=        get_chrome_info(c)



INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',

    'core',

    'django_extensions',
]


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

ROOT_URLCONF = 'core.urls'
APPEND_SLASH = True
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(PYTHON_DIR, 'themes', ACTIVE_THEME),
            os.path.join(PYTHON_DIR, 'themes', 'default'),
            os.path.join(PYTHON_DIR, 'themes'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(OUTPUT_DIR, SQL_INDEX_FILENAME),
    }
}

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

################################################################################
### Security Settings
################################################################################
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_DOMAIN = None
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_AGE = 1209600  # 2 weeks
LOGIN_URL = '/accounts/login/'
LOGOUT_REDIRECT_URL = '/'
PASSWORD_RESET_URL = '/accounts/password_reset/'


SHELL_PLUS = 'ipython'
SHELL_PLUS_PRINT_SQL = False
IPYTHON_ARGUMENTS = ['--no-confirm-exit', '--no-banner']
IPYTHON_KERNEL_DISPLAY_NAME = 'ArchiveBox Django Shell'
if IS_SHELL:
    os.environ['PYTHONSTARTUP'] = os.path.join(PYTHON_DIR, 'core', 'welcome_message.py')


LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = False
USE_L10N = False
USE_TZ = False

DATETIME_FORMAT = 'Y-m-d g:iA'
SHORT_DATETIME_FORMAT = 'Y-m-d h:iA'


EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    os.path.join(PYTHON_DIR, 'themes', ACTIVE_THEME, 'static'),
    os.path.join(PYTHON_DIR, 'themes', 'default', 'static'),
]
