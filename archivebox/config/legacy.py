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
import io
import re
import sys
import json
import shutil

from hashlib import md5
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Type, Tuple, Dict
from subprocess import run, PIPE, DEVNULL, STDOUT, TimeoutExpired
from configparser import ConfigParser

from rich.progress import Progress
from rich.console import Console
from benedict import benedict
from pydantic_pkgr import SemVer

import django
from django.db.backends.sqlite3.base import Database as sqlite3


from .constants import CONSTANTS, TIMEZONE
from .constants import *
from .config_stubs import (
    ConfigValue,
    ConfigDefaultValue,
    ConfigDefaultDict,
)
from ..misc.logging import (
    stderr,
    hint,      # noqa
)

from .defaults import SHELL_CONFIG, GENERAL_CONFIG, ARCHIVING_CONFIG, SERVER_CONFIG, SEARCH_BACKEND_CONFIG, STORAGE_CONFIG
from archivebox.plugins_auth.ldap.apps import LDAP_CONFIG
from archivebox.plugins_extractor.favicon.apps import FAVICON_CONFIG
from archivebox.plugins_extractor.wget.apps import WGET_CONFIG

ANSI = SHELL_CONFIG.ANSI
LDAP = LDAP_CONFIG.LDAP_ENABLED

############################### Config Schema ##################################

CONFIG_SCHEMA: Dict[str, ConfigDefaultDict] = {
    'SHELL_CONFIG': SHELL_CONFIG.as_legacy_config_schema(),

    'SERVER_CONFIG': SERVER_CONFIG.as_legacy_config_schema(),
    
    'GENERAL_CONFIG': GENERAL_CONFIG.as_legacy_config_schema(),

    'ARCHIVING_CONFIG': ARCHIVING_CONFIG.as_legacy_config_schema(),

    'SEARCH_BACKEND_CONFIG': SEARCH_BACKEND_CONFIG.as_legacy_config_schema(),

    'STORAGE_CONFIG': STORAGE_CONFIG.as_legacy_config_schema(),
    
    'LDAP_CONFIG': LDAP_CONFIG.as_legacy_config_schema(),
    
    'FAVICON_CONFIG': FAVICON_CONFIG.as_legacy_config_schema(),
    
    'WGET_CONFIG': WGET_CONFIG.as_legacy_config_schema(),


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
        'GIT_DOMAINS':              {'type': str,   'default': 'github.com,bitbucket.org,gitlab.com,gist.github.com,codeberg.org,gitea.com,git.sr.ht'},
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


        'CURL_ARGS':                {'type': list,  'default': ['--silent',
                                                                '--location',
                                                                '--compressed'
                                                               ]},
        'CURL_EXTRA_ARGS':          {'type': list,  'default': None},
        'GIT_ARGS':                 {'type': list,  'default': ['--recursive']},
        'SINGLEFILE_ARGS':          {'type': list,  'default': None},
        'SINGLEFILE_EXTRA_ARGS':    {'type': list,  'default': None},
    },

    'DEPENDENCY_CONFIG': {
        'USE_CURL':                 {'type': bool,  'default': True},
        'USE_SINGLEFILE':           {'type': bool,  'default': True},
        'USE_READABILITY':          {'type': bool,  'default': True},
        'USE_GIT':                  {'type': bool,  'default': True},
        'USE_CHROME':               {'type': bool,  'default': True},
        'USE_YOUTUBEDL':            {'type': bool,  'default': True},
        'USE_RIPGREP':              {'type': bool,  'default': True},

        'CURL_BINARY':              {'type': str,   'default': 'curl'},
        'GIT_BINARY':               {'type': str,   'default': 'git'},
        'NODE_BINARY':              {'type': str,   'default': 'node'},
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
DYNAMIC_CONFIG_SCHEMA: ConfigDefaultDict = {
    'PACKAGE_DIR':              {'default': lambda c: CONSTANTS.PACKAGE_DIR.resolve()},
    'TEMPLATES_DIR':            {'default': lambda c: c['PACKAGE_DIR'] / CONSTANTS.TEMPLATES_DIR_NAME},
    'CUSTOM_TEMPLATES_DIR':     {'default': lambda c: c['CUSTOM_TEMPLATES_DIR'] and Path(c['CUSTOM_TEMPLATES_DIR'])},


    'URL_DENYLIST_PTN':         {'default': lambda c: c['URL_DENYLIST'] and re.compile(c['URL_DENYLIST'] or '', CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS)},
    'URL_ALLOWLIST_PTN':        {'default': lambda c: c['URL_ALLOWLIST'] and re.compile(c['URL_ALLOWLIST'] or '', CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS)},


    'USE_CURL':                 {'default': lambda c: c['USE_CURL'] and (c['SAVE_FAVICON'] or c['SAVE_TITLE'] or c['SAVE_ARCHIVE_DOT_ORG'])},
    'CURL_VERSION':             {'default': lambda c: bin_version(c['CURL_BINARY']) if c['USE_CURL'] else None},
    # 'CURL_USER_AGENT':          {'default': lambda c: c['CURL_USER_AGENT'].format(**c)},
    'CURL_ARGS':                {'default': lambda c: c['CURL_ARGS'] or []},
    'CURL_EXTRA_ARGS':          {'default': lambda c: c['CURL_EXTRA_ARGS'] or []},
    'SAVE_FAVICON':             {'default': lambda c: c['USE_CURL'] and c['SAVE_FAVICON']},
    'SAVE_ARCHIVE_DOT_ORG':     {'default': lambda c: c['USE_CURL'] and c['SAVE_ARCHIVE_DOT_ORG']},

    'USE_GIT':                  {'default': lambda c: c['USE_GIT'] and c['SAVE_GIT']},
    'GIT_VERSION':              {'default': lambda c: bin_version(c['GIT_BINARY']) if c['USE_GIT'] else None},
    'SAVE_GIT':                 {'default': lambda c: c['USE_GIT'] and c['SAVE_GIT']},


    'DEPENDENCIES':             {'default': lambda c: get_dependency_info(c)},
    # 'CODE_LOCATIONS':           {'default': lambda c: get_code_locations(c)},
    # 'DATA_LOCATIONS':           {'default': lambda c: get_data_locations(c)},

    'SAVE_ALLOWLIST_PTN':       {'default': lambda c: c['SAVE_ALLOWLIST'] and {re.compile(k, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS): v for k, v in c['SAVE_ALLOWLIST'].items()}},
    'SAVE_DENYLIST_PTN':        {'default': lambda c: c['SAVE_DENYLIST'] and {re.compile(k, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS): v for k, v in c['SAVE_DENYLIST'].items()}},
}


# print("FINISHED DEFINING SCHEMAS")

################################### Helpers ####################################


def load_config_val(key: str,
                    default: ConfigDefaultValue=None,
                    type: Optional[Type]=None,
                    aliases: Optional[Tuple[str, ...]]=None,
                    config: Optional[benedict]=None,
                    env_vars: Optional[os._Environ]=None,
                    config_file_vars: Optional[Dict[str, str]]=None) -> ConfigValue:
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
    if config_path.exists():
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

    if not config_path.exists():
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

    if Path(f'{config_path}.bak').exists():
        os.remove(f'{config_path}.bak')

    return benedict({
        key.upper(): CONFIG.get(key.upper())
        for key in config.keys()
    })



def load_config(defaults: ConfigDefaultDict,
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



# Dependency Metadata Helpers
def bin_version(binary: Optional[str], cmd: Optional[str]=None, timeout: int=3) -> Optional[str]:
    """check the presence and return valid version line of a specified binary"""

    abspath = bin_path(binary)
    if not binary or not abspath:
        return None
    
    return '999.999.999'

    # Now handled by new BinProvider plugin system, no longer needed:

    try:
        bin_env = os.environ | {'LANG': 'C'}
        is_cmd_str = cmd and isinstance(cmd, str)
        version_str = (
            run(cmd or [abspath, "--version"], timeout=timeout, shell=is_cmd_str, stdout=PIPE, stderr=STDOUT, env=bin_env)
            .stdout.strip()
            .decode()
        )
        if not version_str:
            version_str = (
                run(cmd or [abspath, "--version"], timeout=timeout, shell=is_cmd_str, stdout=PIPE, stderr=STDOUT)
                .stdout.strip()
                .decode()
            )
        
        # take first 3 columns of first line of version info
        semver = SemVer.parse(version_str)
        if semver:
            return str(semver)
    except (OSError, TimeoutExpired):
        pass
        # stderr(f'[X] Unable to find working version of dependency: {binary}', color='red')
        # stderr('    Make sure it\'s installed, then confirm it\'s working by running:')
        # stderr(f'        {binary} --version')
        # stderr()
        # stderr('    If you don\'t want to install it, you can disable it via config. See here for more info:')
        # stderr('        https://github.com/ArchiveBox/ArchiveBox/wiki/Install')
    return None

def bin_path(binary: Optional[str]) -> Optional[str]:
    if binary is None:
        return None

    node_modules_bin = Path('.') / 'node_modules' / '.bin' / binary
    if node_modules_bin.exists():
        return str(node_modules_bin.resolve())

    return shutil.which(str(Path(binary).expanduser())) or shutil.which(str(binary)) or binary

def bin_hash(binary: Optional[str]) -> Optional[str]:
    return 'UNUSED'
    # DEPRECATED: now handled by new BinProvider plugin system, no longer needed:

    if binary is None:
        return None
    abs_path = bin_path(binary)
    if abs_path is None or not Path(abs_path).exists():
        return None

    file_hash = md5()
    with io.open(abs_path, mode='rb') as f:
        for chunk in iter(lambda: f.read(io.DEFAULT_BUFFER_SIZE), b''):
            file_hash.update(chunk)

    return f'md5:{file_hash.hexdigest()}'

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
    #     if full_path.exists():
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


def get_dependency_info(config: benedict) -> ConfigValue:
    return {
        # 'PYTHON_BINARY': {
        #     'path': bin_path(config['PYTHON_BINARY']),
        #     'version': config['PYTHON_VERSION'],
        #     'hash': bin_hash(config['PYTHON_BINARY']),
        #     'enabled': True,
        #     'is_valid': bool(config['PYTHON_VERSION']),
        # },
        # 'SQLITE_BINARY': {
        #     'path': bin_path(config['SQLITE_BINARY']),
        #     'version': config['SQLITE_VERSION'],
        #     'hash': bin_hash(config['SQLITE_BINARY']),
        #     'enabled': True,
        #     'is_valid': bool(config['SQLITE_VERSION']),
        # },
        # 'DJANGO_BINARY': {
        #     'path': bin_path(config['DJANGO_BINARY']),
        #     'version': config['DJANGO_VERSION'],
        #     'hash': bin_hash(config['DJANGO_BINARY']),
        #     'enabled': True,
        #     'is_valid': bool(config['DJANGO_VERSION']),
        # },
        # 'ARCHIVEBOX_BINARY': {
        #     'path': bin_path(config['ARCHIVEBOX_BINARY']),
        #     'version': config['VERSION'],
        #     'hash': bin_hash(config['ARCHIVEBOX_BINARY']),
        #     'enabled': True,
        #     'is_valid': True,
        # },
        
        'CURL_BINARY': {
            'path': bin_path(config['CURL_BINARY']),
            'version': config['CURL_VERSION'],
            'hash': bin_hash(config['CURL_BINARY']),
            'enabled': config['USE_CURL'],
            'is_valid': bool(config['CURL_VERSION']),
        },
        # 'WGET_BINARY': {
        #     'path': bin_path(config['WGET_BINARY']),
        #     'version': config['WGET_VERSION'],
        #     'hash': bin_hash(config['WGET_BINARY']),
        #     'enabled': config['USE_WGET'],
        #     'is_valid': bool(config['WGET_VERSION']),
        # },
        # 'NODE_BINARY': {
        #     'path': bin_path(config['NODE_BINARY']),
        #     'version': config['NODE_VERSION'],
        #     'hash': bin_hash(config['NODE_BINARY']),
        #     'enabled': config['USE_NODE'],
        #     'is_valid': bool(config['NODE_VERSION']),
        # },
        # 'MERCURY_BINARY': {
        #     'path': bin_path(config['MERCURY_BINARY']),
        #     'version': config['MERCURY_VERSION'],
        #     'hash': bin_hash(config['MERCURY_BINARY']),
        #     'enabled': config['USE_MERCURY'],
        #     'is_valid': bool(config['MERCURY_VERSION']),
        # },
        'GIT_BINARY': {
            'path': bin_path(config['GIT_BINARY']),
            'version': config['GIT_VERSION'],
            'hash': bin_hash(config['GIT_BINARY']),
            'enabled': config['USE_GIT'],
            'is_valid': bool(config['GIT_VERSION']),
        },
        # 'SINGLEFILE_BINARY': {
        #     'path': bin_path(config['SINGLEFILE_BINARY']),
        #     'version': config['SINGLEFILE_VERSION'],
        #     'hash': bin_hash(config['SINGLEFILE_BINARY']),
        #     'enabled': config['USE_SINGLEFILE'],
        #     'is_valid': bool(config['SINGLEFILE_VERSION']),
        # },
        # 'READABILITY_BINARY': {
        #     'path': bin_path(config['READABILITY_BINARY']),
        #     'version': config['READABILITY_VERSION'],
        #     'hash': bin_hash(config['READABILITY_BINARY']),
        #     'enabled': config['USE_READABILITY'],
        #     'is_valid': bool(config['READABILITY_VERSION']),
        # },
        # 'YOUTUBEDL_BINARY': {
        #     'path': bin_path(config['YOUTUBEDL_BINARY']),
        #     'version': config['YOUTUBEDL_VERSION'],
        #     'hash': bin_hash(config['YOUTUBEDL_BINARY']),
        #     'enabled': config['USE_YOUTUBEDL'],
        #     'is_valid': bool(config['YOUTUBEDL_VERSION']),
        # },
        # 'CHROME_BINARY': {
        #     'path': bin_path(config['CHROME_BINARY']),
        #     'version': config['CHROME_VERSION'],
        #     'hash': bin_hash(config['CHROME_BINARY']),
        #     'enabled': config['USE_CHROME'],
        #     'is_valid': bool(config['CHROME_VERSION']),
        # },
        # 'RIPGREP_BINARY': {
        #     'path': bin_path(config['RIPGREP_BINARY']),
        #     'version': config['RIPGREP_VERSION'],
        #     'hash': bin_hash(config['RIPGREP_BINARY']),
        #     'enabled': config['USE_RIPGREP'],
        #     'is_valid': bool(config['RIPGREP_VERSION']),
        # },
        # 'SONIC_BINARY': {
        #     'path': bin_path(config['SONIC_BINARY']),
        #     'version': config['SONIC_VERSION'],
        #     'hash': bin_hash(config['SONIC_BINARY']),
        #     'enabled': config['USE_SONIC'],
        #     'is_valid': bool(config['SONIC_VERSION']),
        # },
    }

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
# this lets us do:  from .config import DEBUG, MEDIA_TIMEOUT, ...

# print("FINISHED LOADING CONFIG USING SCHEMAS + FILE + ENV")

# ******************************************************************************
# ******************************************************************************
# ******************************************************************************
# ******************************************************************************
# ******************************************************************************



########################### System Environment Setup ###########################


# Set timezone to UTC and umask to OUTPUT_PERMISSIONS
assert TIMEZONE == 'UTC', f'The server timezone should always be set to UTC (got {TIMEZONE})'  # noqa: F821
os.environ["TZ"] = TIMEZONE                                                  # noqa: F821
os.umask(0o777 - int(STORAGE_CONFIG.DIR_OUTPUT_PERMISSIONS, base=8))                        # noqa: F821

########################### Config Validity Checkers ###########################

if not SHELL_CONFIG.USE_COLOR:
    os.environ['NO_COLOR'] = '1'
if not SHELL_CONFIG.SHOW_PROGRESS:
    os.environ['TERM'] = 'dumb'

# recreate rich console obj based on new config values
CONSOLE = Console()
from ..misc import logging
logging.CONSOLE = CONSOLE


INITIAL_STARTUP_PROGRESS = None
INITIAL_STARTUP_PROGRESS_TASK = 0

def bump_startup_progress_bar():
    global INITIAL_STARTUP_PROGRESS
    global INITIAL_STARTUP_PROGRESS_TASK
    if INITIAL_STARTUP_PROGRESS:
        INITIAL_STARTUP_PROGRESS.update(INITIAL_STARTUP_PROGRESS_TASK, advance=1)   # type: ignore


def setup_django_minimal():
    # sys.path.append(str(CONSTANTS.PACKAGE_DIR))
    # os.environ.setdefault('ARCHIVEBOX_DATA_DIR', str(CONSTANTS.DATA_DIR))
    # os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    # django.setup()
    raise Exception('dont use this anymore')

DJANGO_SET_UP = False


def setup_django(out_dir: Path | None=None, check_db=False, config: benedict=CONFIG, in_memory_db=False) -> None:
    global INITIAL_STARTUP_PROGRESS
    global INITIAL_STARTUP_PROGRESS_TASK
    global DJANGO_SET_UP

    if DJANGO_SET_UP:
        raise Exception('django is already set up!')

    with Progress(transient=True, expand=True, console=CONSOLE) as INITIAL_STARTUP_PROGRESS:
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
                django.setup()
            
            bump_startup_progress_bar()

            from django.conf import settings
            
            # log startup message to the error log
            with open(settings.ERROR_LOG, "a", encoding='utf-8') as f:
                command = ' '.join(sys.argv)
                ts = datetime.now(timezone.utc).strftime('%Y-%m-%d__%H:%M:%S')
                f.write(f"\n> {command}; TS={ts} VERSION={CONSTANTS.VERSION} IN_DOCKER={SHELL_CONFIG.IN_DOCKER} IS_TTY={SHELL_CONFIG.IS_TTY}\n")

            if check_db:
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
                assert sql_index_path.exists(), (
                    f'No database file {sql_index_path} found in: {CONSTANTS.DATA_DIR} (Are you in an ArchiveBox collection directory?)')

                bump_startup_progress_bar()

                # https://docs.pydantic.dev/logfire/integrations/django/ Logfire Debugging
                if settings.DEBUG_LOGFIRE:
                    from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
                    SQLite3Instrumentor().instrument()

                    import logfire

                    logfire.configure()
                    logfire.instrument_django(is_sql_commentor_enabled=True)
                    logfire.info(f'Started ArchiveBox v{CONSTANTS.VERSION}', argv=sys.argv)

        except KeyboardInterrupt:
            raise SystemExit(2)
        
    DJANGO_SET_UP = True

    INITIAL_STARTUP_PROGRESS = None
    INITIAL_STARTUP_PROGRESS_TASK = None
