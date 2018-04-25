import os
import sys
import shutil

from configparser import ConfigParser
import pkg_resources
from subprocess import run, PIPE

user_config_path = os.path.expanduser('~/.config/bookmark-archiver/user.conf')

config_files = [
    '/etc/bookmark-archiver/archiver.conf',
    user_config_path,
]

config = ConfigParser()
config.read(
    config_files,
    encoding='utf8',
)

IS_TTY = sys.stdout.isatty()

USE_COLOR = config['tty'].getboolean('color')
SHOW_PROGRESS = config['tty'].getboolean('progres')

FETCH_WGET = config['wget'].getboolean('enabled')
FETCH_WGET_REQUISITES = config['wget'].getboolean('requisites')

FETCH_AUDIO = config['youtubedl:audio'].getboolean('enabled')
FETCH_VIDEO = config['youtubedl:video'].getboolean('enabled')

FETCH_PDF = config['website:pdf'].getboolean('enabled')
FETCH_SCREENSHOT = config['website'].getboolean('screenshot')
FETCH_FAVICON = config['website'].getboolean('favicon')
SUBMIT_ARCHIVE_DOT_ORG = config['archive.org'].getboolean('submit')

RESOLUTION = config['website:pdf']['resolution']
CHECK_SSL_VALIDITY = config['ssl'].get_boolean('enabled')

ARCHIVE_PERMISSIONS = config['archive']['permission']
ARCHIVE_DIR = config['archive']['dir']

CHROME_BINARY = config['chrome']['command']
CHROME_USER_DATA_DIR = config['chrome']['userdata']

WGET_BINARY = config['wget']['command']
WGET_USER_AGENT = config['wget']['useragent']
TIMEOUT = config['website:pdf']['timeout']


LINK_INDEX_TEMPLATE = pkg_resources.resource_filename(__name__, 'templates/link_index.html')
INDEX_TEMPLATE = pkg_resources.resource_filename(__name__, 'templates/index.html')
INDEX_ROW_TEMPLATE = pkg_resources.resource_filename(__name__, 'templates/index_row.html')
TEMPLATE_STATICFILES = config['template']['static']

# Output Paths
ROOT_FOLDER = os.path.dirname(os.path.abspath(__file__))
HTML_FOLDER = config['archive']['html folder']
ARCHIVE_FOLDER = config['archive']['archive folder']
os.chdir(ROOT_FOLDER)

FOOTER_INFO = os.getenv('FOOTER_INFO',
        'Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.',
)
# ******************************************************************************
# ********************** Do not edit below this point **************************
# ******************************************************************************

### Terminal Configuration
TERM_WIDTH = shutil.get_terminal_size((100, 10)).columns
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

### Confirm Environment Setup
try:
    GIT_SHA = run(["git", "rev-list", "-1", "HEAD", "./"], stdout=PIPE, cwd=ROOT_FOLDER).stdout.strip().decode()
except Exception:
    GIT_SHA = None
    print('[!] Warning, you need git installed for some archiving features to save correct version numbers!')

if sys.stdout.encoding.upper() != 'UTF-8':
    print('[X] Your system is running python3 scripts with a bad locale setting: {} (it should be UTF-8).'.format(sys.stdout.encoding))
    print('    To fix it, add the line "export PYTHONIOENCODING=utf8" to your ~/.bashrc file (without quotes)')
    print('')
    print('    Confirm that it\'s fixed by opening a new shell and running:')
    print('        python3 -c "import sys; print(sys.stdout.encoding)"   # should output UTF-8')
    print('')
    print('    Alternatively, run this script with:')
    print('        env PYTHONIOENCODING=utf8 ./archive.py export.html')
