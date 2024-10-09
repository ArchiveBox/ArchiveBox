"""
ArchiveBox config definitons (including defaults and dynamic config options).

Config Usage Example:

    archivebox config --set MEDIA_TIMEOUT=600
    env MEDIA_TIMEOUT=600 USE_COLOR=False ... archivebox [subcommand] ...

Config Precedence Order:

  1. cli args                 (--update-all / --index-only / etc.)
  2. shell environment vars   (env USE_COLOR=False archivebox add '...')
  3. config file              (echo "SAVE_FAVICON=False" >> ArchiveBox.conf)
  4. defaults                 (defined below in Python)

Documentation:

  https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration

"""

__package__ = 'archivebox.config'

import os
import re
import sys
import json
import shutil

from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Type, Tuple, Dict, Any
from subprocess import run, DEVNULL
from configparser import ConfigParser

from rich.progress import Progress
from rich.console import Console
from benedict import benedict

import django
from django.db.backends.sqlite3.base import Database as sqlite3


from .constants import CONSTANTS
from .constants import *

from ..misc.logging import (
    stderr,
    hint,      # noqa
)

from .common import SHELL_CONFIG, GENERAL_CONFIG, ARCHIVING_CONFIG, SERVER_CONFIG, SEARCH_BACKEND_CONFIG, STORAGE_CONFIG
from archivebox.plugins_auth.ldap.apps import LDAP_CONFIG
from archivebox.plugins_extractor.favicon.apps import FAVICON_CONFIG
from archivebox.plugins_extractor.wget.apps import WGET_CONFIG
from archivebox.plugins_extractor.curl.apps import CURL_CONFIG

ANSI = SHELL_CONFIG.ANSI
LDAP = LDAP_CONFIG.LDAP_ENABLED

############################### Config Schema ##################################

CONFIG_SCHEMA: Dict[str, Dict[str, Any]] = {
    'SHELL_CONFIG': SHELL_CONFIG.as_legacy_config_schema(),

    'SERVER_CONFIG': SERVER_CONFIG.as_legacy_config_schema(),
    
    'GENERAL_CONFIG': GENERAL_CONFIG.as_legacy_config_schema(),

    'ARCHIVING_CONFIG': ARCHIVING_CONFIG.as_legacy_config_schema(),

    'SEARCH_BACKEND_CONFIG': SEARCH_BACKEND_CONFIG.as_legacy_config_schema(),

    'STORAGE_CONFIG': STORAGE_CONFIG.as_legacy_config_schema(),
    
    'LDAP_CONFIG': LDAP_CONFIG.as_legacy_config_schema(),
    
    # 'FAVICON_CONFIG': FAVICON_CONFIG.as_legacy_config_schema(),
    
    # 'WGET_CONFIG': WGET_CONFIG.as_legacy_config_schema(),
    
    # 'CURL_CONFIG': CURL_CONFIG.as_legacy_config_schema(),


    'ARCHIVE_METHOD_TOGGLES': {
        'SAVE_TITLE':               {'type': bool,  'default': True, 'aliases': ('FETCH_TITLE',)},
        'SAVE_FAVICON':             {'type': bool,  'default': True, 'aliases': ('FETCH_FAVICON',)},
        'SAVE_WGET':                {'type': bool,  'default': True, 'aliases': ('FETCH_WGET',)},
        'SAVE_WGET_REQUISITES':     {'type': bool,  'default': True, 'aliases': ('FETCH_WGET_REQUISITES',)},
        'SAVE_SINGLEFILE':          {'type': bool,  'default': True, 'aliases': ('FETCH_SINGLEFILE',)},
        'SAVE_READABILITY':         {'type': bool,  'default': True, 'aliases': ('FETCH_READABILITY',)},
        'SAVE_MERCURY':             {'type': bool,  'default': True, 'aliases': ('FETCH_MERCURY',)},
        'SAVE_HTMLTOTEXT':          {'type': bool,  'default': True, 'aliases': ('FETCH_HTMLTOTEXT',)},
        'SAVE_PDF':                 {'type': bool,  'default': True, 'aliases': ('FETCH_PDF',)},
        'SAVE_SCREENSHOT':          {'type': bool,  'default': True, 'aliases': ('FETCH_SCREENSHOT',)},
        'SAVE_DOM':                 {'type': bool,  'default': True, 'aliases': ('FETCH_DOM',)},
        'SAVE_HEADERS':             {'type': bool,  'default': True, 'aliases': ('FETCH_HEADERS',)},
        'SAVE_WARC':                {'type': bool,  'default': True, 'aliases': ('FETCH_WARC',)},
        'SAVE_GIT':                 {'type': bool,  'default': True, 'aliases': ('FETCH_GIT',)},
        'SAVE_MEDIA':               {'type': bool,  'default': True, 'aliases': ('FETCH_MEDIA',)},
        'SAVE_ARCHIVE_DOT_ORG':     {'type': bool,  'default': True, 'aliases': ('SUBMIT_ARCHIVE_DOT_ORG',)},
        'SAVE_ALLOWLIST':           {'type': dict,  'default': {},},
        'SAVE_DENYLIST':            {'type': dict,  'default': {},},
    },

    'ARCHIVE_METHOD_OPTIONS': {
        'RESOLUTION':               {'type': str,   'default': '1440,2000', 'aliases': ('SCREENSHOT_RESOLUTION','WINDOW_SIZE')},
        # 'GIT_DOMAINS':              {'type': str,   'default': 'github.com,bitbucket.org,gitlab.com,gist.github.com,codeberg.org,gitea.com,git.sr.ht'},
        'CHECK_SSL_VALIDITY':       {'type': bool,  'default': True},
        'MEDIA_MAX_SIZE':           {'type': str,   'default': '750m'},

        'USER_AGENT':               {'type': str,   'default': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 ArchiveBox/{VERSION} (+https://github.com/ArchiveBox/ArchiveBox/)'},
        'CURL_USER_AGENT':          {'type': str,   'default': lambda c: c['USER_AGENT']}, # + ' curl/{CURL_VERSION}'},

        'COOKIES_FILE':             {'type': str,   'default': None},

        'YOUTUBEDL_ARGS':           {'type': list,  'default': lambda c: [
                                                                '--restrict-filenames',
                                                                '--trim-filenames', '128',
                                                                '--write-description',
                                                                '--write-info-json',
                                                                '--write-annotations',
                                                                '--write-thumbnail',
                                                                '--no-call-home',
                                                                '--write-sub',
                                                                '--write-auto-subs',
                                                                '--convert-subs=srt',
                                                                '--yes-playlist',
                                                                '--continue',
                                                                # This flag doesn't exist in youtube-dl
                                                                # only in yt-dlp
                                                                '--no-abort-on-error',
                                                                # --ignore-errors must come AFTER
                                                                # --no-abort-on-error
                                                                # https://github.com/yt-dlp/yt-dlp/issues/4914
                                                                '--ignore-errors',
                                                                '--geo-bypass',
                                                                '--add-metadata',
                                                                '--format=(bv*+ba/b)[filesize<={}][filesize_approx<=?{}]/(bv*+ba/b)'.format(c['MEDIA_MAX_SIZE'], c['MEDIA_MAX_SIZE']),
                                                                ]},
        'YOUTUBEDL_EXTRA_ARGS':     {'type': list,  'default': None},

    },

    'DEPENDENCY_CONFIG': {
        'USE_CURL':                 {'type': bool,  'default': True},
        'USE_SINGLEFILE':           {'type': bool,  'default': True},
        'USE_READABILITY':          {'type': bool,  'default': True},
        'USE_GIT':                  {'type': bool,  'default': True},
        'USE_CHROME':               {'type': bool,  'default': True},
        'USE_YOUTUBEDL':            {'type': bool,  'default': True},
        'USE_RIPGREP':              {'type': bool,  'default': True},

        # 'GIT_BINARY':               {'type': str,   'default': 'git'},
        # 'CURL_BINARY':              {'type': str,   'default': 'curl'},
        # 'NODE_BINARY':              {'type': str,   'default': 'node'},
        # 'YOUTUBEDL_BINARY':         {'type': str,   'default': 'yt-dlp'},   # also can accept youtube-dl
        # 'SINGLEFILE_BINARY':        {'type': str,   'default': lambda c: bin_path('single-file')},
        # 'READABILITY_BINARY':       {'type': str,   'default': lambda c: bin_path('readability-extractor')},
        # 'RIPGREP_BINARY':           {'type': str,   'default': 'rg'},

        'POCKET_CONSUMER_KEY':      {'type': str,   'default': None},
        'POCKET_ACCESS_TOKENS':     {'type': dict,  'default': {}},

        'READWISE_READER_TOKENS':   {'type': dict,  'default': {}},
    },
}


########################## Backwards-Compatibility #############################


# for backwards compatibility with old config files, check old/deprecated names for each key
CONFIG_ALIASES = {
    alias: key
    for section in CONFIG_SCHEMA.values()
        for key, default in section.items()
            for alias in default.get('aliases', ())
}
USER_CONFIG = {key: section[key] for section in CONFIG_SCHEMA.values() for key in section.keys()}

def get_real_name(key: str) -> str:
    """get the current canonical name for a given deprecated config key"""
    return CONFIG_ALIASES.get(key.upper().strip(), key.upper().strip())



# These are derived/computed values calculated *after* all user-provided config values are ingested
# they appear in `archivebox config` output and are intended to be read-only for the user
DYNAMIC_CONFIG_SCHEMA: Dict[str, Any] = {
    'URL_DENYLIST_PTN':         {'default': lambda c: c['URL_DENYLIST'] and re.compile(c['URL_DENYLIST'] or '', CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS)},
    'URL_ALLOWLIST_PTN':        {'default': lambda c: c['URL_ALLOWLIST'] and re.compile(c['URL_ALLOWLIST'] or '', CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS)},

    'SAVE_ALLOWLIST_PTN':       {'default': lambda c: c['SAVE_ALLOWLIST'] and {re.compile(k, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS): v for k, v in c['SAVE_ALLOWLIST'].items()}},
    'SAVE_DENYLIST_PTN':        {'default': lambda c: c['SAVE_DENYLIST'] and {re.compile(k, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS): v for k, v in c['SAVE_DENYLIST'].items()}},
}


# print("FINISHED DEFINING SCHEMAS")

################################### Helpers ####################################


def load_config_val(key: str,
                    default: Any=None,
                    type: Optional[Type]=None,
                    aliases: Optional[Tuple[str, ...]]=None,
                    config: Optional[benedict]=None,
                    env_vars: Optional[os._Environ]=None,
                    config_file_vars: Optional[Dict[str, str]]=None) -> Any:
    """parse bool, int, and str key=value pairs from env"""

    assert isinstance(config, dict)

    is_read_only = type is None
    if is_read_only:
        if callable(default):
            return default(config)
        return default

    # get value from environment variables or config files
    config_keys_to_check = (key, *(aliases or ()))
    val = None
    for key in config_keys_to_check:
        if env_vars:
            val = env_vars.get(key)
            if val:
                break

        if config_file_vars:
            val = config_file_vars.get(key)
            if val:
                break

    is_unset = val is None
    if is_unset:
        if callable(default):
            return default(config)
        return default

    # calculate value based on expected type
    BOOL_TRUEIES = ('true', 'yes', '1')
    BOOL_FALSEIES = ('false', 'no', '0')

    if type is bool:
        if val.lower() in BOOL_TRUEIES:
            return True
        elif val.lower() in BOOL_FALSEIES:
            return False
        else:
            raise ValueError(f'Invalid configuration option {key}={val} (expected a boolean: True/False)')

    elif type is str:
        if val.lower() in (*BOOL_TRUEIES, *BOOL_FALSEIES):
            raise ValueError(f'Invalid configuration option {key}={val} (expected a string, but value looks like a boolean)')
        return val.strip()

    elif type is int:
        if not val.strip().isdigit():
            raise ValueError(f'Invalid configuration option {key}={val} (expected an integer)')
        return int(val.strip())

    elif type is list or type is dict:
        return json.loads(val)

    raise Exception('Config values can only be str, bool, int, or json')


def load_config_file(out_dir: str | None=CONSTANTS.DATA_DIR) -> Optional[benedict]:
    """load the ini-formatted config file from DATA_DIR/Archivebox.conf"""

    config_path = CONSTANTS.CONFIG_FILE
    if os.access(config_path, os.R_OK):
        config_file = ConfigParser()
        config_file.optionxform = str
        config_file.read(config_path)
        # flatten into one namespace
        config_file_vars = benedict({
            key.upper(): val
            for section, options in config_file.items()
                for key, val in options.items()
        })
        # print('[i] Loaded config file', os.path.abspath(config_path))
        # print(config_file_vars)
        return config_file_vars
    return None


def write_config_file(config: Dict[str, str], out_dir: str | None=CONSTANTS.DATA_DIR) -> benedict:
    """load the ini-formatted config file from DATA_DIR/Archivebox.conf"""

    from archivebox.misc.system import atomic_write

    CONFIG_HEADER = (
    """# This is the config file for your ArchiveBox collection.
    #
    # You can add options here manually in INI format, or automatically by running:
    #    archivebox config --set KEY=VALUE
    #
    # If you modify this file manually, make sure to update your archive after by running:
    #    archivebox init
    #
    # A list of all possible config with documentation and examples can be found here:
    #    https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration

    """)

    config_path = CONSTANTS.CONFIG_FILE

    if not os.access(config_path, os.F_OK):
        atomic_write(config_path, CONFIG_HEADER)

    config_file = ConfigParser()
    config_file.optionxform = str
    config_file.read(config_path)

    with open(config_path, 'r', encoding='utf-8') as old:
        atomic_write(f'{config_path}.bak', old.read())

    find_section = lambda key: [name for name, opts in CONFIG_SCHEMA.items() if key in opts][0]

    # Set up sections in empty config file
    for key, val in config.items():
        section = find_section(key)
        if section in config_file:
            existing_config = dict(config_file[section])
        else:
            existing_config = {}
        config_file[section] = benedict({**existing_config, key: val})

    # always make sure there's a SECRET_KEY defined for Django
    existing_secret_key = None
    if 'SERVER_CONFIG' in config_file and 'SECRET_KEY' in config_file['SERVER_CONFIG']:
        existing_secret_key = config_file['SERVER_CONFIG']['SECRET_KEY']

    if (not existing_secret_key) or ('not a valid secret' in existing_secret_key):
        from django.utils.crypto import get_random_string
        chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'
        random_secret_key = get_random_string(50, chars)
        if 'SERVER_CONFIG' in config_file:
            config_file['SERVER_CONFIG']['SECRET_KEY'] = random_secret_key
        else:
            config_file['SERVER_CONFIG'] = {'SECRET_KEY': random_secret_key}

    with open(config_path, 'w+', encoding='utf-8') as new:
        config_file.write(new)

    try:
        # validate the config by attempting to re-parse it
        CONFIG = load_all_config()
    except BaseException:                                                       # lgtm [py/catch-base-exception]
        # something went horribly wrong, rever to the previous version
        with open(f'{config_path}.bak', 'r', encoding='utf-8') as old:
            atomic_write(config_path, old.read())

        raise

    if os.access(f'{config_path}.bak', os.F_OK):
        os.remove(f'{config_path}.bak')

    return benedict({
        key.upper(): CONFIG.get(key.upper())
        for key in config.keys()
    })



def load_config(defaults: Dict[str, Any],
                config: Optional[benedict]=None,
                out_dir: Optional[str]=None,
                env_vars: Optional[os._Environ]=None,
                config_file_vars: Optional[Dict[str, str]]=None) -> benedict:

    env_vars = env_vars or os.environ
    config_file_vars = config_file_vars or load_config_file(out_dir=out_dir)

    extended_config = benedict(config.copy() if config else {})
    for key, default in defaults.items():
        try:
            # print('LOADING CONFIG KEY:', key, 'DEFAULT=', default)
            extended_config[key] = load_config_val(
                key,
                default=default['default'],
                type=default.get('type'),
                aliases=default.get('aliases'),
                config=extended_config,
                env_vars=env_vars,
                config_file_vars=config_file_vars,
            )
        except KeyboardInterrupt:
            raise SystemExit(0)
        except Exception as e:
            stderr()
            stderr(f'[X] Error while loading configuration value: {key}', color='red', config=extended_config)
            stderr('    {}: {}'.format(e.__class__.__name__, e))
            stderr()
            stderr('    Check your config for mistakes and try again (your archive data is unaffected).')
            stderr()
            stderr('    For config documentation and examples see:')
            stderr('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration')
            stderr()
            # raise
            # raise SystemExit(2)

    return benedict(extended_config)



def find_chrome_binary() -> Optional[str]:
    """find any installed chrome binaries in the default locations"""
    # Precedence: Chromium, Chrome, Beta, Canary, Unstable, Dev
    # make sure data dir finding precedence order always matches binary finding order
    default_executable_paths = (
        # '~/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium',
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

def find_chrome_data_dir() -> Optional[str]:
    """find any installed chrome user data directories in the default locations"""
    # deprecated because this is DANGEROUS, do not re-implement/uncomment this behavior.

    # Going forward we want to discourage people from using their main chrome profile for archiving.
    # Session tokens, personal data, and cookies are often returned in server responses,
    # when they get archived, they are essentially burned as anyone who can view the archive
    # can use that data to masquerade as the logged-in user that did the archiving.
    # For this reason users should always create dedicated burner profiles for archiving and not use
    # their daily driver main accounts.

    # # Precedence: Chromium, Chrome, Beta, Canary, Unstable, Dev
    # # make sure data dir finding precedence order always matches binary finding order
    # default_profile_paths = (
    #     '~/.config/chromium',
    #     '~/Library/Application Support/Chromium',
    #     '~/AppData/Local/Chromium/User Data',
    #     '~/.config/chrome',
    #     '~/.config/google-chrome',
    #     '~/Library/Application Support/Google/Chrome',
    #     '~/AppData/Local/Google/Chrome/User Data',
    #     '~/.config/google-chrome-stable',
    #     '~/.config/google-chrome-beta',
    #     '~/Library/Application Support/Google/Chrome Canary',
    #     '~/AppData/Local/Google/Chrome SxS/User Data',
    #     '~/.config/google-chrome-unstable',
    #     '~/.config/google-chrome-dev',
    # )
    # for path in default_profile_paths:
    #     full_path = Path(path).resolve()
    #     if full_path.is_dir():
    #         return full_path
    return None

def wget_supports_compression(config):
    try:
        cmd = [
            config['WGET_BINARY'],
            "--compression=auto",
            "--help",
        ]
        return not run(cmd, stdout=DEVNULL, stderr=DEVNULL).returncode
    except (FileNotFoundError, OSError):
        return False


# ******************************************************************************
# ******************************************************************************
# ******************************** Load Config *********************************
# ******* (compile the defaults, configs, and metadata all into CONFIG) ********
# ******************************************************************************
# ******************************************************************************


def load_all_config():
    CONFIG = benedict()
    for section_name, section_config in CONFIG_SCHEMA.items():
        # print('LOADING CONFIG SECTION:', section_name)
        CONFIG = load_config(section_config, CONFIG)

    # print("LOADING CONFIG SECTION:", 'DYNAMIC')
    return load_config(DYNAMIC_CONFIG_SCHEMA, CONFIG)

# add all final config values in CONFIG to globals in this file
CONFIG: benedict = load_all_config()
globals().update(CONFIG)


# print("FINISHED LOADING CONFIG USING SCHEMAS + FILE + ENV")

# ******************************************************************************
# ******************************************************************************
# ******************************************************************************
# ******************************************************************************
# ******************************************************************************



########################### System Environment Setup ###########################


# Set timezone to UTC and umask to OUTPUT_PERMISSIONS
assert CONSTANTS.TIMEZONE == 'UTC', f'The server timezone should always be set to UTC (got {CONSTANTS.TIMEZONE})'  # noqa: F821
os.environ["TZ"] = CONSTANTS.TIMEZONE                                                  # noqa: F821
os.umask(0o777 - int(STORAGE_CONFIG.DIR_OUTPUT_PERMISSIONS, base=8))                        # noqa: F821

########################### Config Validity Checkers ###########################

if not SHELL_CONFIG.USE_COLOR:
    os.environ['NO_COLOR'] = '1'
if not SHELL_CONFIG.SHOW_PROGRESS:
    os.environ['TERM'] = 'dumb'

# recreate rich console obj based on new config values
STDOUT = CONSOLE = Console()
STDERR = Console(stderr=True)
from ..misc import logging
logging.CONSOLE = CONSOLE


INITIAL_STARTUP_PROGRESS = None
INITIAL_STARTUP_PROGRESS_TASK = 0

def bump_startup_progress_bar(advance=1):
    global INITIAL_STARTUP_PROGRESS
    global INITIAL_STARTUP_PROGRESS_TASK
    if INITIAL_STARTUP_PROGRESS:
        INITIAL_STARTUP_PROGRESS.update(INITIAL_STARTUP_PROGRESS_TASK, advance=advance)   # type: ignore


def setup_django_minimal():
    # sys.path.append(str(CONSTANTS.PACKAGE_DIR))
    # os.environ.setdefault('ARCHIVEBOX_DATA_DIR', str(CONSTANTS.DATA_DIR))
    # os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    # django.setup()
    raise Exception('dont use this anymore')

DJANGO_SET_UP = False


def setup_django(out_dir: Path | None=None, check_db=False, config: benedict=CONFIG, in_memory_db=False) -> None:
    from rich.panel import Panel
    
    global INITIAL_STARTUP_PROGRESS
    global INITIAL_STARTUP_PROGRESS_TASK
    global DJANGO_SET_UP

    if DJANGO_SET_UP:
        # raise Exception('django is already set up!')
        # TODO: figure out why CLI entrypoints with init_pending are running this twice sometimes
        return

    with Progress(transient=True, expand=True, console=STDERR) as INITIAL_STARTUP_PROGRESS:
        INITIAL_STARTUP_PROGRESS_TASK = INITIAL_STARTUP_PROGRESS.add_task("[green]Loading modules...", total=25)

        output_dir = out_dir or CONSTANTS.DATA_DIR

        assert isinstance(output_dir, Path) and isinstance(CONSTANTS.PACKAGE_DIR, Path)

        bump_startup_progress_bar()
        try:
            from django.core.management import call_command
                
            bump_startup_progress_bar()

            if in_memory_db:
                raise Exception('dont use this anymore')
            
                # some commands (e.g. oneshot) dont store a long-lived sqlite3 db file on disk.
                # in those cases we create a temporary in-memory db and run the migrations
                # immediately to get a usable in-memory-database at startup
                os.environ.setdefault("ARCHIVEBOX_DATABASE_NAME", ":memory:")
                django.setup()
                
                bump_startup_progress_bar()
                call_command("migrate", interactive=False, verbosity=0)
            else:
                # Otherwise use default sqlite3 file-based database and initialize django
                # without running migrations automatically (user runs them manually by calling init)
                try:
                    django.setup()
                except Exception as e:
                    bump_startup_progress_bar(advance=1000)
                    
                    subcommand = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
                    if subcommand not in ('help', 'version', '--help', '--version'):
                        # show error message to user only if they're not running a meta command / just trying to get help
                        STDERR.print()
                        STDERR.print(Panel(
                            f'\n[red]{e.__class__.__name__}[/red]: [yellow]{e}[/yellow]\nPlease check your config and [blue]DATA_DIR[/blue] permissions.\n',
                            title='\n\n[red][X] Error while trying to load database![/red]',
                            subtitle='[grey53]NO WRITES CAN BE PERFORMED[/grey53]',
                            expand=False,
                            style='bold red',
                        ))
                        STDERR.print()
                        STDERR.print_exception(show_locals=False)
                    return
            
            bump_startup_progress_bar()

            from django.conf import settings
            
            # log startup message to the error log
            with open(settings.ERROR_LOG, "a", encoding='utf-8') as f:
                command = ' '.join(sys.argv)
                ts = datetime.now(timezone.utc).strftime('%Y-%m-%d__%H:%M:%S')
                f.write(f"\n> {command}; TS={ts} VERSION={CONSTANTS.VERSION} IN_DOCKER={SHELL_CONFIG.IN_DOCKER} IS_TTY={SHELL_CONFIG.IS_TTY}\n")

            if check_db:
                # make sure the data dir is owned by a non-root user
                if CONSTANTS.DATA_DIR.stat().st_uid == 0:
                    STDERR.print('[red][X] Error: ArchiveBox DATA_DIR cannot be owned by root![/red]')
                    STDERR.print(f'    {CONSTANTS.DATA_DIR}')
                    STDERR.print()
                    STDERR.print('[violet]Hint:[/violet] Are you running archivebox in the right folder? (and as a non-root user?)')
                    STDERR.print('    cd path/to/your/archive/data')
                    STDERR.print('    archivebox [command]')
                    STDERR.print()
                    raise SystemExit(9)
                
                # Create cache table in DB if needed
                try:
                    from django.core.cache import cache
                    cache.get('test', None)
                except django.db.utils.OperationalError:
                    call_command("createcachetable", verbosity=0)

                bump_startup_progress_bar()

                # if archivebox gets imported multiple times, we have to close
                # the sqlite3 whenever we init from scratch to avoid multiple threads
                # sharing the same connection by accident
                from django.db import connections
                for conn in connections.all():
                    conn.close_if_unusable_or_obsolete()

                sql_index_path = CONSTANTS.DATABASE_FILE
                assert os.access(sql_index_path, os.F_OK), (
                    f'No database file {sql_index_path} found in: {CONSTANTS.DATA_DIR} (Are you in an ArchiveBox collection directory?)')

                bump_startup_progress_bar()

                # https://docs.pydantic.dev/logfire/integrations/django/ Logfire Debugging
                # if settings.DEBUG_LOGFIRE:
                #     from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
                #     SQLite3Instrumentor().instrument()

                #     import logfire

                #     logfire.configure()
                #     logfire.instrument_django(is_sql_commentor_enabled=True)
                #     logfire.info(f'Started ArchiveBox v{CONSTANTS.VERSION}', argv=sys.argv)

        except KeyboardInterrupt:
            raise SystemExit(2)
        
    DJANGO_SET_UP = True

    INITIAL_STARTUP_PROGRESS = None
    INITIAL_STARTUP_PROGRESS_TASK = None
