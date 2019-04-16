import os
import re
import sys
import shutil

from subprocess import run, PIPE, DEVNULL

# ******************************************************************************
# Documentation: https://github.com/pirate/ArchiveBox/wiki/Configuration
# Use the 'env' command to pass config options to ArchiveBox.  e.g.:
#     env USE_COLOR=True CHROME_BINARY=google-chrome ./archive export.html
# ******************************************************************************

IS_TTY =                 sys.stdout.isatty()
USE_COLOR =              os.getenv('USE_COLOR',              str(IS_TTY)        ).lower() == 'true'
SHOW_PROGRESS =          os.getenv('SHOW_PROGRESS',          str(IS_TTY)        ).lower() == 'true'
ONLY_NEW =               os.getenv('ONLY_NEW',               'False'            ).lower() == 'true'
MEDIA_TIMEOUT =          int(os.getenv('MEDIA_TIMEOUT',      '3600'))
TIMEOUT =                int(os.getenv('TIMEOUT',            '60'))
OUTPUT_PERMISSIONS =     os.getenv('OUTPUT_PERMISSIONS',     '755'              )
FOOTER_INFO =            os.getenv('FOOTER_INFO',            'Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.',)

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
WGET_USER_AGENT =        os.getenv('WGET_USER_AGENT',        'ArchiveBox/{GIT_SHA} (+https://github.com/pirate/ArchiveBox/) wget/{WGET_VERSION}')
COOKIES_FILE =           os.getenv('COOKIES_FILE',           None)
CHROME_USER_DATA_DIR =   os.getenv('CHROME_USER_DATA_DIR',   None)
CHROME_HEADLESS =        os.getenv('CHROME_HEADLESS',        'True'             ).lower() == 'true'
CHROME_USER_AGENT =      os.getenv('CHROME_USER_AGENT',      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36')

FIREFOX_HEADLESS =       os.getenv('FIREFOX_HEADLESS',       'True'             ).lower() == 'true'
FIREFOX_PROFILE =        os.getenv('FIREFOX_PROFILE',        'ArchiveBox'       )
FIREFOX_RESOLUTION =     os.getenv('FIREFOX_RESOLUTION',     None               )

CURL_BINARY =            os.getenv('CURL_BINARY',            'curl')
GIT_BINARY =             os.getenv('GIT_BINARY',             'git')
WGET_BINARY =            os.getenv('WGET_BINARY',            'wget')
YOUTUBEDL_BINARY =       os.getenv('YOUTUBEDL_BINARY',       'youtube-dl')
CHROME_BINARY =          os.getenv('CHROME_BINARY',          None)
FIREFOX_BINARY =         os.getenv('FIREFOX_BINARY',         None)

URL_BLACKLIST =          os.getenv('URL_BLACKLIST',          None)

try:
    OUTPUT_DIR = os.path.abspath(os.getenv('OUTPUT_DIR'))
except Exception:
    OUTPUT_DIR = None


# ******************************************************************************
# **************************** Derived Settings ********************************
# ******************************************************************************

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
if not OUTPUT_DIR:
    OUTPUT_DIR = os.path.join(REPO_DIR, 'output')

ARCHIVE_DIR_NAME = 'archive'
SOURCES_DIR_NAME = 'sources'
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, ARCHIVE_DIR_NAME)
SOURCES_DIR = os.path.join(OUTPUT_DIR, SOURCES_DIR_NAME)

PYTHON_PATH = os.path.join(REPO_DIR, 'archivebox')
TEMPLATES_DIR = os.path.join(PYTHON_PATH, 'templates')

CHROME_SANDBOX = os.getenv('CHROME_SANDBOX', 'True').lower() == 'true'
USE_WGET = FETCH_WGET or FETCH_WGET_REQUISITES or FETCH_WARC
WGET_AUTO_COMPRESSION = USE_WGET and WGET_BINARY and (not run([WGET_BINARY, "--compression=auto", "--help"], stdout=DEVNULL, stderr=DEVNULL).returncode)

URL_BLACKLIST = URL_BLACKLIST and re.compile(URL_BLACKLIST, re.IGNORECASE)

########################### Environment & Dependencies #########################

try:
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


    if not CHROME_BINARY:
        # Precedence: Chromium, Chrome, Beta, Canary, Unstable, Dev
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
                CHROME_BINARY = name
                break
        else:
            CHROME_BINARY = 'chromium-browser'
    # print('[i] Using Chrome binary: {}'.format(shutil.which(CHROME_BINARY) or CHROME_BINARY))

    if CHROME_USER_DATA_DIR is None:
        # Precedence: Chromium, Chrome, Beta, Canary, Unstable, Dev
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
                CHROME_USER_DATA_DIR = full_path
                break
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

    
    if not FIREFOX_BINARY:
        # Precedence: Stable, Developer Edition, Nightly
        # Missing paths to Developer Edition on linux, Nightly on MacOS
        default_executable_paths = (
            'firefox',
            '/Applications/Firefox.app/Contents/MacOS/Firefox',
            '/Applications/FirefoxDeveloperEdition.app/Contents/MacOS/Firefox',
            'firefox-nightly',
        )
        for name in default_executable_paths:
            full_path_exists = shutil.which(name)
            if full_path_exists:
                FIREFOX_BINARY = name
                break
        else:
            FIREFOX_BINARY = 'firefox'
    # print('[i] Using Firefox binary: {}'.format(shutil.which(FIREFOX_BINARY) or FIREFOX_BINARY))
    
    FIREFOX_OPTIONS = {
        'FIREFOX_BINARY': FIREFOX_BINARY,
        'FIREFOX_HEADLESS': FIREFOX_HEADLESS,
        'FIREFOX_PROFILE': FIREFOX_PROFILE,
        'FIREFOX_RESOLUTION': FIREFOX_RESOLUTION,
    }

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

    ### Get code version by parsing git log
    GIT_SHA = 'unknown'
    try:
        GIT_SHA = run([GIT_BINARY, 'rev-list', '-1', 'HEAD', './'], stdout=PIPE, cwd=REPO_DIR).stdout.strip().decode()
    except Exception:
        print('[!] Warning: unable to determine git version, is git installed and in your $PATH?')

    ### Get absolute path for cookies file
    try:
        COOKIES_FILE = os.path.abspath(COOKIES_FILE) if COOKIES_FILE else None
    except Exception:
        print('[!] Warning: unable to get full path to COOKIES_FILE, are you sure you specified it correctly?')
        raise

    ### Make sure curl is installed
    if FETCH_FAVICON or SUBMIT_ARCHIVE_DOT_ORG:
        if run(['which', CURL_BINARY], stdout=DEVNULL, stderr=DEVNULL).returncode or run([CURL_BINARY, '--version'], stdout=DEVNULL, stderr=DEVNULL).returncode:
            print('{red}[X] Missing dependency: curl{reset}'.format(**ANSI))
            print('    Install it, then confirm it works with: {} --version'.format(CURL_BINARY))
            print('    See https://github.com/pirate/ArchiveBox/wiki/Install for help.')
            raise SystemExit(1)

    ### Make sure wget is installed and calculate version
    if FETCH_WGET or FETCH_WARC:
        if run(['which', WGET_BINARY], stdout=DEVNULL, stderr=DEVNULL).returncode or run([WGET_BINARY, '--version'], stdout=DEVNULL, stderr=DEVNULL).returncode:
            print('{red}[X] Missing dependency: wget{reset}'.format(**ANSI))
            print('    Install it, then confirm it works with: {} --version'.format(WGET_BINARY))
            print('    See https://github.com/pirate/ArchiveBox/wiki/Install for help.')
            raise SystemExit(1)

        WGET_VERSION = 'unknown'
        try:
            wget_vers_str = run([WGET_BINARY, "--version"], stdout=PIPE, cwd=REPO_DIR).stdout.strip().decode()
            WGET_VERSION = wget_vers_str.split('\n')[0].split(' ')[2]
        except Exception:
            if USE_WGET:
                print('[!] Warning: unable to determine wget version, is wget installed and in your $PATH?')

        WGET_USER_AGENT = WGET_USER_AGENT.format(GIT_SHA=GIT_SHA[:9], WGET_VERSION=WGET_VERSION)

    ### Checks if chrome is installed and calculate version
    if run(['which', CHROME_BINARY], stdout=DEVNULL, stderr=DEVNULL).returncode:
        CHROME_AVAILABLE = False
    else:
        CHROME_AVAILABLE = True
    
    if CHROME_AVAILABLE:
        # parse chrome --version e.g. Google Chrome 61.0.3114.0 canary / Chromium 59.0.3029.110 built on Ubuntu, running on Ubuntu 16.04
        try:
            result = run([CHROME_BINARY, '--version'], stdout=PIPE)
            version_str = result.stdout.decode('utf-8')
            version_lines = re.sub("(Google Chrome|Chromium) (\\d+?)\\.(\\d+?)\\.(\\d+?).*?$", "\\2", version_str).split('\n')
            version = [l for l in version_lines if l.isdigit()][-1]
            if int(version) < 59:
                CHROME_AVAILABLE = False
                print(version_lines)
                print('{red}[X] Chrome version must be 59 or greater for headless PDF, screenshot, and DOM saving{reset}'.format(**ANSI))
                print('    See https://github.com/pirate/ArchiveBox/wiki/Install for help.')
        except (IndexError, TypeError, OSError):
            CHROME_AVAILABLE = False
            print('{red}[X] Failed to parse Chrome version, is it installed properly?{reset}'.format(**ANSI))
            print('    Install it, then confirm it works with: {} --version'.format(CHROME_BINARY))
            print('    See https://github.com/pirate/ArchiveBox/wiki/Install for help.')

    ### Checks if firefox is installed and calculates version
    if run(['which', FIREFOX_BINARY], stdout=DEVNULL, stderr=DEVNULL).returncode:
        FIREFOX_AVAILABLE = False
    else:
        FIREFOX_AVAILABLE = True

    if FIREFOX_AVAILABLE:
        # parse firefox --version e.g. Mozilla Firefox 66.0.3
        try:
            result = run([FIREFOX_BINARY, '--version'], stdout=PIPE)
            version_str = result.stdout.decode('utf-8').strip()
            version_matches = re.match("Mozilla Firefox (\d+)\.(\d+)\.(\d+)", version_str)
            major_version = version_matches.group(1)
            if int(major_version) < 57: 
                FIREFOX_AVAILABLE = False
                print(version_str)
                print('{red}[X] Firefox version must be 57 or greater for headless screenshot.{reset}'.format(**ANSI))
        except (IndexError, TypeError, OSError):
            FIREFOX_AVAILABLE = False
            print('{red}[X] Failed to parse Firefox version, is it installed properly?{reset}'.format(**ANSI))
            print('    Install it, then confirm it works with: {} --version'.format(FIREFOX_BINARY))
            print('    See https://github.com/pirate/ArchiveBox/wiki/Install for help.')

    ### Make sure git is installed
    if FETCH_GIT:
        if run(['which', GIT_BINARY], stdout=DEVNULL, stderr=DEVNULL).returncode or run([GIT_BINARY, '--version'], stdout=DEVNULL, stderr=DEVNULL).returncode:
            print('{red}[X] Missing dependency: git{reset}'.format(**ANSI))
            print('    Install it, then confirm it works with: {} --version'.format(GIT_BINARY))
            print('    See https://github.com/pirate/ArchiveBox/wiki/Install for help.')
            raise SystemExit(1)

    ### Make sure youtube-dl is installed
    if FETCH_MEDIA:
        if run(['which', YOUTUBEDL_BINARY], stdout=DEVNULL, stderr=DEVNULL).returncode or run([YOUTUBEDL_BINARY, '--version'], stdout=DEVNULL, stderr=DEVNULL).returncode:
            print('{red}[X] Missing dependency: youtube-dl{reset}'.format(**ANSI))
            print('    Install it, then confirm it was installed with: {} --version'.format(YOUTUBEDL_BINARY))
            print('    See https://github.com/pirate/ArchiveBox/wiki/Install for help.')
            raise SystemExit(1)

    if FETCH_PDF or FETCH_DOM:
        if not CHROME_AVAILABLE:
            print('{}[X] Missing dependency: {}{}'.format(ANSI['red'], CHROME_BINARY, ANSI['reset']))
            print('    Install it, then confirm it works with: {} --version'.format(CHROME_BINARY))
            print('    See https://github.com/pirate/ArchiveBox/wiki/Install for help.')
            raise SystemExit(1)

    if FETCH_SCREENSHOT:
        if (not CHROME_AVAILABLE) and (not FIREFOX_AVAILABLE):
            print('{}[X] Missing FETCH_SCREENSHOT dependency: {} or {}{}'.format(ANSI['red'], CHROME_BINARY, FIREFOX_BINARY, ANSI['reset']))
            print('    Install any of them, then confirm it works with: {} --version or '.format(CHROME_BINARY, FIREFOX_BINARY))
            print('    See https://github.com/pirate/ArchiveBox/wiki/Install for help.')
            raise SystemExit(1)


except KeyboardInterrupt:
    raise SystemExit(1)

except:
    print('[X] There was an error during the startup procedure, your archive data is unaffected.')
    raise
