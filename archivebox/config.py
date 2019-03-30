import os
import re
import sys
import shutil

from typing import Optional, Pattern
from subprocess import run, PIPE, DEVNULL


OUTPUT_DIR: str
URL_BLACKLIST: Optional[Pattern[str]]

# ******************************************************************************
# Documentation: https://github.com/pirate/ArchiveBox/wiki/Configuration
# Use the 'env' command to pass config options to ArchiveBox.  e.g.:
#     env USE_COLOR=True CHROME_BINARY=google-chrome ./archive export.html
# ******************************************************************************

IS_TTY =                 sys.stdout.isatty()
USE_COLOR =              os.getenv('USE_COLOR',              str(IS_TTY)        ).lower() == 'true'
SHOW_PROGRESS =          os.getenv('SHOW_PROGRESS',          str(IS_TTY)        ).lower() == 'true'

OUTPUT_DIR =             os.getenv('OUTPUT_DIR',             '')
ONLY_NEW =               os.getenv('ONLY_NEW',               'False'            ).lower() == 'true'
TIMEOUT =                int(os.getenv('TIMEOUT',            '60'))
MEDIA_TIMEOUT =          int(os.getenv('MEDIA_TIMEOUT',      '3600'))
OUTPUT_PERMISSIONS =     os.getenv('OUTPUT_PERMISSIONS',     '755'              )
FOOTER_INFO =            os.getenv('FOOTER_INFO',            'Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.',)
URL_BLACKLIST =          os.getenv('URL_BLACKLIST',          None)

FETCH_WGET =             os.getenv('FETCH_WGET',             'True'             ).lower() == 'true'
FETCH_WGET_REQUISITES =  os.getenv('FETCH_WGET_REQUISITES',  'True'             ).lower() == 'true'
FETCH_PDF =              os.getenv('FETCH_PDF',              'True'             ).lower() == 'true'
FETCH_SCREENSHOT =       os.getenv('FETCH_SCREENSHOT',       'True'             ).lower() == 'true'
FETCH_DOM =              os.getenv('FETCH_DOM',              'True'             ).lower() == 'true'
FETCH_WARC =             os.getenv('FETCH_WARC',             'True'             ).lower() == 'true'
FETCH_GIT =              os.getenv('FETCH_GIT',              'True'             ).lower() == 'true'
FETCH_MEDIA =            os.getenv('FETCH_MEDIA',            'True'             ).lower() == 'true'
FETCH_FAVICON =          os.getenv('FETCH_FAVICON',          'True'             ).lower() == 'true'
FETCH_TITLE =            os.getenv('FETCH_TITLE',            'True'             ).lower() == 'true'
SUBMIT_ARCHIVE_DOT_ORG = os.getenv('SUBMIT_ARCHIVE_DOT_ORG', 'True'             ).lower() == 'true'

CHECK_SSL_VALIDITY =     os.getenv('CHECK_SSL_VALIDITY',     'True'             ).lower() == 'true'
RESOLUTION =             os.getenv('RESOLUTION',             '1440,2000'        )
GIT_DOMAINS =            os.getenv('GIT_DOMAINS',            'github.com,bitbucket.org,gitlab.com').split(',')
WGET_USER_AGENT =        os.getenv('WGET_USER_AGENT',        'ArchiveBox/{VERSION} (+https://github.com/pirate/ArchiveBox/) wget/{WGET_VERSION}')
COOKIES_FILE =           os.getenv('COOKIES_FILE',           None)
CHROME_USER_DATA_DIR =   os.getenv('CHROME_USER_DATA_DIR',   None)
CHROME_HEADLESS =        os.getenv('CHROME_HEADLESS',        'True'             ).lower() == 'true'
CHROME_USER_AGENT =      os.getenv('CHROME_USER_AGENT',      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36')

USE_CURL =               os.getenv('USE_CURL',               'True'             ).lower() == 'true'
USE_WGET =               os.getenv('USE_WGET',               'True'             ).lower() == 'true'
USE_CHROME =             os.getenv('USE_CHROME',             'True'             ).lower() == 'true'

CURL_BINARY =            os.getenv('CURL_BINARY',            'curl')
GIT_BINARY =             os.getenv('GIT_BINARY',             'git')
WGET_BINARY =            os.getenv('WGET_BINARY',            'wget')
YOUTUBEDL_BINARY =       os.getenv('YOUTUBEDL_BINARY',       'youtube-dl')
CHROME_BINARY =          os.getenv('CHROME_BINARY',          None)

CHROME_SANDBOX =         os.getenv('CHROME_SANDBOX', 'True').lower() == 'true'

try:
    OUTPUT_DIR = os.path.abspath(os.getenv('OUTPUT_DIR'))
except Exception:
    OUTPUT_DIR = None

# ******************************************************************************

### Terminal Configuration
TERM_WIDTH = lambda: shutil.get_terminal_size((100, 10)).columns
ANSI = {
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
if not USE_COLOR:
    # dont show colors if USE_COLOR is False
    ANSI = {k: '' for k in ANSI.keys()}


REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
if OUTPUT_DIR:
    OUTPUT_DIR = os.path.abspath(OUTPUT_DIR)
else:
    OUTPUT_DIR = os.path.abspath(os.curdir)

ARCHIVE_DIR_NAME = 'archive'
SOURCES_DIR_NAME = 'sources'
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, ARCHIVE_DIR_NAME)
SOURCES_DIR = os.path.join(OUTPUT_DIR, SOURCES_DIR_NAME)

PYTHON_DIR = os.path.join(REPO_DIR, 'archivebox')
TEMPLATES_DIR = os.path.join(PYTHON_DIR, 'templates')

if COOKIES_FILE:
    COOKIES_FILE = os.path.abspath(COOKIES_FILE)

URL_BLACKLIST = URL_BLACKLIST and re.compile(URL_BLACKLIST, re.IGNORECASE)

########################### Environment & Dependencies #########################

VERSION = open(os.path.join(PYTHON_DIR, 'VERSION'), 'r').read().strip()
GIT_SHA = VERSION.split('+')[1]

### Check Python environment
python_vers = float('{}.{}'.format(sys.version_info.major, sys.version_info.minor))
if python_vers < 3.5:
    print('{}[X] Python version is not new enough: {} (>3.5 is required){}'.format(ANSI['red'], python_vers, ANSI['reset']))
    print('    See https://github.com/pirate/ArchiveBox/wiki/Troubleshooting#python for help upgrading your Python installation.')
    raise SystemExit(1)

if sys.stdout.encoding.upper() not in ('UTF-8', 'UTF8'):
    print('[X] Your system is running python3 scripts with a bad locale setting: {} (it should be UTF-8).'.format(sys.stdout.encoding))
    print('    To fix it, add the line "export PYTHONIOENCODING=UTF-8" to your ~/.bashrc file (without quotes)')
    print('')
    print('    Confirm that it\'s fixed by opening a new shell and running:')
    print('        python3 -c "import sys; print(sys.stdout.encoding)"   # should output UTF-8')
    print('')
    print('    Alternatively, run this script with:')
    print('        env PYTHONIOENCODING=UTF-8 ./archive.py export.html')

# ******************************************************************************
# ***************************** Helper Functions *******************************
# ******************************************************************************

def bin_version(binary: str) -> str:
    """check the presence and return valid version line of a specified binary"""
    if not shutil.which(binary):
        print('{red}[X] Missing dependency: wget{reset}'.format(**ANSI))
        print('    Install it, then confirm it works with: {} --version'.format(binary))
        print('    See https://github.com/pirate/ArchiveBox/wiki/Install for help.')
        raise SystemExit(1)
    
    try:
        version_str = run([binary, "--version"], stdout=PIPE, cwd=REPO_DIR).stdout.strip().decode()
        return version_str.split('\n')[0].strip()
    except Exception:
        print('{red}[X] Unable to find a working version of {cmd}, is it installed and in your $PATH?'.format(cmd=binary, **ANSI))
        raise SystemExit(1)


def find_chrome_binary() -> Optional[str]:
    """find any installed chrome binaries in the default locations"""
    # Precedence: Chromium, Chrome, Beta, Canary, Unstable, Dev
    # make sure data dir finding precedence order always matches binary finding order
    default_executable_paths = (
        'chromium-browser',
        'chromium',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
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
    
    print('{red}[X] Unable to find a working version of Chrome/Chromium, is it installed and in your $PATH?'.format(**ANSI))
    raise SystemExit(1)


def find_chrome_data_dir() -> Optional[str]:
    """find any installed chrome user data directories in the default locations"""
    # Precedence: Chromium, Chrome, Beta, Canary, Unstable, Dev
    # make sure data dir finding precedence order always matches binary finding order
    default_profile_paths = (
        '~/.config/chromium',
        '~/Library/Application Support/Chromium',
        '~/AppData/Local/Chromium/User Data',
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
        full_path = os.path.expanduser(path)
        if os.path.exists(full_path):
            return full_path
    return None


# ******************************************************************************
# ************************ Environment & Dependencies **************************
# ******************************************************************************

try:
    ### Make sure curl is installed
    if USE_CURL:
        USE_CURL = FETCH_FAVICON or SUBMIT_ARCHIVE_DOT_ORG
    else:
        FETCH_FAVICON = SUBMIT_ARCHIVE_DOT_ORG = False
    CURL_VERSION = None
    if USE_CURL:
        CURL_VERSION = bin_version(CURL_BINARY)

    ### Make sure wget is installed and calculate version
    if USE_WGET:
        USE_WGET = FETCH_WGET or FETCH_WARC
    else:
        FETCH_WGET = FETCH_WARC = False
    WGET_VERSION = None
    WGET_AUTO_COMPRESSION = False
    if USE_WGET:
        WGET_VERSION = bin_version(WGET_BINARY)
        WGET_AUTO_COMPRESSION = not run([WGET_BINARY, "--compression=auto", "--help"], stdout=DEVNULL).returncode
        
    WGET_USER_AGENT = WGET_USER_AGENT.format(
        VERSION=VERSION,
        WGET_VERSION=WGET_VERSION or '',
    )

    ### Make sure git is installed
    GIT_VERSION = None
    if FETCH_GIT:
        GIT_VERSION = bin_version(GIT_BINARY)

    ### Make sure youtube-dl is installed
    YOUTUBEDL_VERSION = None
    if FETCH_MEDIA:
        YOUTUBEDL_VERSION = bin_version(YOUTUBEDL_BINARY)

    ### Make sure chrome is installed and calculate version
    if USE_CHROME:
        USE_CHROME = FETCH_PDF or FETCH_SCREENSHOT or FETCH_DOM
    else:
        FETCH_PDF = FETCH_SCREENSHOT = FETCH_DOM = False
    
    if CHROME_BINARY is None:
        CHROME_BINARY = find_chrome_binary() or 'chromium-browser'
    CHROME_VERSION = None
    if USE_CHROME:
        if CHROME_BINARY:
            CHROME_VERSION = bin_version(CHROME_BINARY)
            # print('[i] Using Chrome binary: {}'.format(shutil.which(CHROME_BINARY) or CHROME_BINARY))

            if CHROME_USER_DATA_DIR is None:
                CHROME_USER_DATA_DIR = find_chrome_data_dir()
            # print('[i] Using Chrome data dir: {}'.format(os.path.abspath(CHROME_USER_DATA_DIR)))

    CHROME_OPTIONS = {
        'TIMEOUT': TIMEOUT,
        'RESOLUTION': RESOLUTION,
        'CHECK_SSL_VALIDITY': CHECK_SSL_VALIDITY,
        'CHROME_BINARY': CHROME_BINARY,
        'CHROME_HEADLESS': CHROME_HEADLESS,
        'CHROME_SANDBOX': CHROME_SANDBOX,
        'CHROME_USER_AGENT': CHROME_USER_AGENT,
        'CHROME_USER_DATA_DIR': CHROME_USER_DATA_DIR,
    }
    # PYPPETEER_ARGS = {
    #     'headless': CHROME_HEADLESS,
    #     'ignoreHTTPSErrors': not CHECK_SSL_VALIDITY,
    #     # 'executablePath': CHROME_BINARY,
    # }
except KeyboardInterrupt:
    raise SystemExit(1)

except:
    print('[X] There was an error while reading configuration. Your archive data is unaffected.')
    raise
