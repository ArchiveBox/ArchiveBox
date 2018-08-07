import os
import sys
import shutil

from subprocess import run, PIPE

IS_TTY = sys.stdout.isatty()

def parse_boolean_env(var, default_value):
    """Parse string environment variables into booleans."""
    return os.getenv(var, default_value)

# ******************************************************************************
# * TO SET YOUR CONFIGURATION, EDIT THE VALUES BELOW, or use the 'env' command *
# * e.g.      *
# * env USE_COLOR=True CHROME_BINARY=google-chrome ./archive.py export.html    *
# ******************************************************************************
CHECK_SSL_VALIDITY     = parse_boolean_env('CHECK_SSL_VALIDITY'     , 'True')
CHROME_BINARY          = os.getenv('CHROME_BINARY'                  , 'chromium-browser')  # change to google-chrome browser if using google-chrome
CHROME_USER_DATA_DIR   = os.getenv('CHROME_USER_DATA_DIR'           , None)
FETCH_AUDIO            = parse_boolean_env('FETCH_AUDIO'            , 'False')
FETCH_DOM              = parse_boolean_env('FETCH_DOM'              , 'True')
FETCH_FAVICON          = parse_boolean_env('FETCH_FAVICON'          , 'True')
FETCH_PDF              = parse_boolean_env('FETCH_PDF'              , 'True')
FETCH_SCREENSHOT       = parse_boolean_env('FETCH_SCREENSHOT'       , 'True')
FETCH_VIDEO            = parse_boolean_env('FETCH_VIDEO'            , 'False')
FETCH_WGET             = parse_boolean_env('FETCH_WGET'             , 'True')
FETCH_WGET_REQUISITES  = parse_boolean_env('FETCH_WGET_REQUISITES'  , 'True')
FOOTER_INFO            = os.getenv('FOOTER_INFO'                    , 'Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.')
OUTPUT_PERMISSIONS     = os.getenv('OUTPUT_PERMISSIONS'             , '755' )
RESOLUTION             = os.getenv('RESOLUTION'                     , '1440,1200')
SHOW_PROGRESS          = parse_boolean_env('SHOW_PROGRESS'          , str(IS_TTY))
SUBMIT_ARCHIVE_DOT_ORG = parse_boolean_env('SUBMIT_ARCHIVE_DOT_ORG' , 'True')
TIMEOUT                = int(os.getenv('TIMEOUT'                    , '60'))
USE_COLOR              = parse_boolean_env('USE_COLOR'              , str(IS_TTY))
WGET_BINARY            = os.getenv('WGET_BINARY'                    , 'wget')
WGET_USER_AGENT        = os.getenv('WGET_USER_AGENT'                , 'Bookmark Archiver')

### Paths
REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

OUTPUT_DIR = os.path.join(REPO_DIR, 'output')
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, 'archive')
SOURCES_DIR = os.path.join(OUTPUT_DIR, 'sources')

PYTHON_PATH = os.path.join(REPO_DIR, 'archiver')
TEMPLATES_DIR = os.path.join(PYTHON_PATH, 'templates')

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
    GIT_SHA = run(["git", "rev-list", "-1", "HEAD", "./"], stdout=PIPE, cwd=REPO_DIR).stdout.strip().decode()
except Exception:
    GIT_SHA = 'unknown'
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
