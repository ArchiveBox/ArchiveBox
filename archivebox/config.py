import os
import sys
import shutil

from subprocess import run, PIPE

# ******************************************************************************
# * TO SET YOUR CONFIGURATION, EDIT THE VALUES BELOW, or use the 'env' command *
# * e.g.                                                                       *
# * env USE_COLOR=True CHROME_BINARY=google-chrome ./archive.py export.html    *
# ******************************************************************************

IS_TTY = sys.stdout.isatty()
ONLY_NEW =               os.getenv('ONLY_NEW',               'False'            ).lower() == 'true'
USE_COLOR =              os.getenv('USE_COLOR',              str(IS_TTY)        ).lower() == 'true'
SHOW_PROGRESS =          os.getenv('SHOW_PROGRESS',          str(IS_TTY)        ).lower() == 'true'
OUTPUT_PERMISSIONS =     os.getenv('OUTPUT_PERMISSIONS',     '755'              )
MEDIA_TIMEOUT =          int(os.getenv('MEDIA_TIMEOUT',      '3600'))
TIMEOUT =                int(os.getenv('TIMEOUT',            '60'))

FETCH_WGET =             os.getenv('FETCH_WGET',             'True'             ).lower() == 'true'
FETCH_WGET_REQUISITES =  os.getenv('FETCH_WGET_REQUISITES',  'True'             ).lower() == 'true'
FETCH_PDF =              os.getenv('FETCH_PDF',              'True'             ).lower() == 'true'
FETCH_SCREENSHOT =       os.getenv('FETCH_SCREENSHOT',       'True'             ).lower() == 'true'
FETCH_DOM =              os.getenv('FETCH_DOM',              'True'             ).lower() == 'true'
FETCH_WARC =             os.getenv('FETCH_WARC',             'True'             ).lower() == 'true'
FETCH_GIT =              os.getenv('FETCH_GIT',              'True'             ).lower() == 'true'
FETCH_MEDIA =            os.getenv('FETCH_MEDIA',            'False'            ).lower() == 'true'
FETCH_FAVICON =          os.getenv('FETCH_FAVICON',          'True'             ).lower() == 'true'
SUBMIT_ARCHIVE_DOT_ORG = os.getenv('SUBMIT_ARCHIVE_DOT_ORG', 'True'             ).lower() == 'true'

CHECK_SSL_VALIDITY =     os.getenv('CHECK_SSL_VALIDITY',     'True'             ).lower() == 'true'
RESOLUTION =             os.getenv('RESOLUTION',             '1440,2000'        )
GIT_DOMAINS =            os.getenv('GIT_DOMAINS',            'github.com,bitbucket.org,gitlab.com').split(',')
WGET_USER_AGENT =        os.getenv('WGET_USER_AGENT',        'ArchiveBox/{GIT_SHA} (+https://github.com/pirate/ArchiveBox/) wget/{WGET_VERSION}')
CHROME_USER_DATA_DIR =   os.getenv('CHROME_USER_DATA_DIR',    None)

CHROME_BINARY =          os.getenv('CHROME_BINARY',          None)  # change to google-chrome browser if using google-chrome
WGET_BINARY =            os.getenv('WGET_BINARY',            'wget'             )
FOOTER_INFO =            os.getenv('FOOTER_INFO',            'Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.',)

### Paths
REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

OUTPUT_DIR = os.path.abspath(os.getenv('OUTPUT_DIR', os.path.join(REPO_DIR, 'output')))
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, 'archive')
SOURCES_DIR = os.path.join(OUTPUT_DIR, 'sources')

PYTHON_PATH = os.path.join(REPO_DIR, 'archivebox')
TEMPLATES_DIR = os.path.join(PYTHON_PATH, 'templates')

# ******************************************************************************
# ********************** Do not edit below this point **************************
# ******************************************************************************

CHROME_SANDBOX =        os.getenv('CHROME_SANDBOX',         'True'             ).lower() == 'true'

if not CHROME_BINARY:
    common_chrome_executable_names = (
        'chromium-browser',
        'chromium',
        'google-chrome',
        'google-chrome-beta',
        'google-chrome-canary',
        'google-chrome-dev',
        'google-chrome-unstable',
    )
    for name in common_chrome_executable_names:
        full_path_exists = shutil.which(name)
        if full_path_exists:
            CHROME_BINARY = name
            break
    else:
        CHROME_BINARY = 'chromium-browser'

# print('[i] Using Chrome binary: {}'.format(shutil.which(CHROME_BINARY) or CHROME_BINARY))

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
GIT_SHA = 'unknown'
try:
    GIT_SHA = run(["git", "rev-list", "-1", "HEAD", "./"], stdout=PIPE, cwd=REPO_DIR).stdout.strip().decode()
except Exception:
    print('[!] Warning: unable to determine git version, is git installed and in your $PATH?')

WGET_VERSION = 'unknown'
try:
    wget_vers_str = run(["wget", "--version"], stdout=PIPE, cwd=REPO_DIR).stdout.strip().decode()
    WGET_VERSION = wget_vers_str.split('\n')[0].split(' ')[2]
except Exception:
    print('[!] Warning: unable to determine wget version, is wget installed and in your $PATH?')

WGET_USER_AGENT = WGET_USER_AGENT.format(GIT_SHA=GIT_SHA[:9], WGET_VERSION=WGET_VERSION)

if sys.stdout.encoding.upper() not in ('UTF-8', 'UTF8'):
    print('[X] Your system is running python3 scripts with a bad locale setting: {} (it should be UTF-8).'.format(sys.stdout.encoding))
    print('    To fix it, add the line "export PYTHONIOENCODING=UTF-8" to your ~/.bashrc file (without quotes)')
    print('')
    print('    Confirm that it\'s fixed by opening a new shell and running:')
    print('        python3 -c "import sys; print(sys.stdout.encoding)"   # should output UTF-8')
    print('')
    print('    Alternatively, run this script with:')
    print('        env PYTHONIOENCODING=UTF-8 ./archive.py export.html')

