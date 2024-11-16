__package__ = 'archivebox.config'

import re
import sys
import shutil
from typing import Dict, Optional, List
from pathlib import Path

from rich import print
from pydantic import Field, field_validator
from django.utils.crypto import get_random_string

from abx_spec_config.base_configset import BaseConfigSet

from .constants import CONSTANTS
from .version import get_COMMIT_HASH, get_BUILD_TIME, VERSION
from .permissions import IN_DOCKER

###################### Config ##########################


class ShellConfig(BaseConfigSet):
    DEBUG: bool                         = Field(default=lambda: '--debug' in sys.argv)
    
    IS_TTY: bool                        = Field(default=sys.stdout.isatty())
    USE_COLOR: bool                     = Field(default=lambda c: c.IS_TTY)
    SHOW_PROGRESS: bool                 = Field(default=lambda c: c.IS_TTY)
    
    IN_DOCKER: bool                     = Field(default=IN_DOCKER)
    IN_QEMU: bool                       = Field(default=False)

    ANSI: Dict[str, str]                = Field(default=lambda c: CONSTANTS.DEFAULT_CLI_COLORS if c.USE_COLOR else CONSTANTS.DISABLED_CLI_COLORS)

    @property
    def TERM_WIDTH(self) -> int:
        if not self.IS_TTY:
            return 200
        return shutil.get_terminal_size((140, 10)).columns
    
    @property
    def COMMIT_HASH(self) -> Optional[str]:
        return get_COMMIT_HASH()
    
    @property
    def BUILD_TIME(self) -> str:
        return get_BUILD_TIME()
 

SHELL_CONFIG = ShellConfig()


class StorageConfig(BaseConfigSet):
    # TMP_DIR must be a local, fast, readable/writable dir by archivebox user,
    # must be a short path due to unix path length restrictions for socket files (<100 chars)
    # must be a local SSD/tmpfs for speed and because bind mounts/network mounts/FUSE dont support unix sockets
    TMP_DIR: Path                       = Field(default=CONSTANTS.DEFAULT_TMP_DIR)
    
    # LIB_DIR must be a local, fast, readable/writable dir by archivebox user,
    # must be able to contain executable binaries (up to 5GB size)
    # should not be a remote/network/FUSE mount for speed reasons, otherwise extractors will be slow
    LIB_DIR: Path                       = Field(default=CONSTANTS.DEFAULT_LIB_DIR)
    
    OUTPUT_PERMISSIONS: str             = Field(default='644')
    RESTRICT_FILE_NAMES: str            = Field(default='windows')
    ENFORCE_ATOMIC_WRITES: bool         = Field(default=True)
    
    # not supposed to be user settable:
    DIR_OUTPUT_PERMISSIONS: str         = Field(default=lambda c: c['OUTPUT_PERMISSIONS'].replace('6', '7').replace('4', '5'))


STORAGE_CONFIG = StorageConfig()


class GeneralConfig(BaseConfigSet):
    TAG_SEPARATOR_PATTERN: str          = Field(default=r'[,]')

GENERAL_CONFIG = GeneralConfig()


class ServerConfig(BaseConfigSet):
    SECRET_KEY: str                     = Field(default=lambda: get_random_string(50, 'abcdefghijklmnopqrstuvwxyz0123456789_'))
    BIND_ADDR: str                      = Field(default=lambda: ['127.0.0.1:8000', '0.0.0.0:8000'][SHELL_CONFIG.IN_DOCKER])
    ALLOWED_HOSTS: str                  = Field(default='*')
    CSRF_TRUSTED_ORIGINS: str           = Field(default=lambda c: 'http://localhost:8000,http://127.0.0.1:8000,http://0.0.0.0:8000,http://{}'.format(c.BIND_ADDR))
    
    SNAPSHOTS_PER_PAGE: int             = Field(default=40)
    PREVIEW_ORIGINALS: bool             = Field(default=True)
    FOOTER_INFO: str                    = Field(default='Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.')
    # CUSTOM_TEMPLATES_DIR: Path          = Field(default=None)  # this is now a constant

    PUBLIC_INDEX: bool                  = Field(default=True)
    PUBLIC_SNAPSHOTS: bool              = Field(default=True)
    PUBLIC_ADD_VIEW: bool               = Field(default=False)
    
    ADMIN_USERNAME: str                 = Field(default=None)
    ADMIN_PASSWORD: str                 = Field(default=None)
    
    REVERSE_PROXY_USER_HEADER: str      = Field(default='Remote-User')
    REVERSE_PROXY_WHITELIST: str        = Field(default='')
    LOGOUT_REDIRECT_URL: str            = Field(default='/')
    
SERVER_CONFIG = ServerConfig()


class ArchivingConfig(BaseConfigSet):
    ONLY_NEW: bool                        = Field(default=True)
    
    TIMEOUT: int                          = Field(default=60)
    MEDIA_TIMEOUT: int                    = Field(default=3600)

    MEDIA_MAX_SIZE: str                   = Field(default='750m')
    RESOLUTION: str                       = Field(default='1440,2000')
    CHECK_SSL_VALIDITY: bool              = Field(default=True)
    USER_AGENT: str                       = Field(default=f'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 ArchiveBox/{VERSION} (+https://github.com/ArchiveBox/ArchiveBox/)')
    COOKIES_FILE: Path | None             = Field(default=None)
    
    URL_DENYLIST: str                     = Field(default=r'\.(css|js|otf|ttf|woff|woff2|gstatic\.com|googleapis\.com/css)(\?.*)?$', alias='URL_BLACKLIST')
    URL_ALLOWLIST: str | None             = Field(default=None, alias='URL_WHITELIST')
    
    SAVE_ALLOWLIST: Dict[str, List[str]]  = Field(default={})  # mapping of regex patterns to list of archive methods
    SAVE_DENYLIST: Dict[str, List[str]]   = Field(default={})
    
    DEFAULT_PERSONA: str                  = Field(default='Default')
    
    # GIT_DOMAINS: str                    = Field(default='github.com,bitbucket.org,gitlab.com,gist.github.com,codeberg.org,gitea.com,git.sr.ht')
    # WGET_USER_AGENT: str                = Field(default=lambda c: c['USER_AGENT'] + ' wget/{WGET_VERSION}')
    # CURL_USER_AGENT: str                = Field(default=lambda c: c['USER_AGENT'] + ' curl/{CURL_VERSION}')
    # CHROME_USER_AGENT: str              = Field(default=lambda c: c['USER_AGENT'])
    # CHROME_USER_DATA_DIR: str | None    = Field(default=None)
    # CHROME_TIMEOUT: int                 = Field(default=0)
    # CHROME_HEADLESS: bool               = Field(default=True)
    # CHROME_SANDBOX: bool                = Field(default=lambda: not SHELL_CONFIG.IN_DOCKER)

    def validate(self):
        if int(self.TIMEOUT) < 5:
            print(f'[red][!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={self.TIMEOUT} seconds)[/red]', file=sys.stderr)
            print('    You must allow *at least* 5 seconds for indexing and archive methods to run succesfully.', file=sys.stderr)
            print('    (Setting it to somewhere between 30 and 3000 seconds is recommended)', file=sys.stderr)
            print(file=sys.stderr)
            print('    If you want to make ArchiveBox run faster, disable specific archive methods instead:', file=sys.stderr)
            print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#archive-method-toggles', file=sys.stderr)
            print(file=sys.stderr)
    
    @field_validator('CHECK_SSL_VALIDITY', mode='after')
    def validate_check_ssl_validity(cls, v):
        """SIDE EFFECT: disable "you really shouldnt disable ssl" warnings emitted by requests"""
        if not v:
            import requests
            import urllib3
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return v
    
    @property
    def URL_ALLOWLIST_PTN(self) -> re.Pattern | None:
        return re.compile(self.URL_ALLOWLIST, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS) if self.URL_ALLOWLIST else None
    
    @property
    def URL_DENYLIST_PTN(self) -> re.Pattern:
        return re.compile(self.URL_DENYLIST, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS)
    
    @property
    def SAVE_ALLOWLIST_PTNS(self) -> Dict[re.Pattern, List[str]]:
        return {
            # regexp: methods list
            re.compile(key, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS): val
            for key, val in self.SAVE_ALLOWLIST.items()
        } if self.SAVE_ALLOWLIST else {}
    
    @property
    def SAVE_DENYLIST_PTNS(self) -> Dict[re.Pattern, List[str]]:
        return {
            # regexp: methods list
            re.compile(key, CONSTANTS.ALLOWDENYLIST_REGEX_FLAGS): val
            for key, val in self.SAVE_DENYLIST.items()
        } if self.SAVE_DENYLIST else {}

ARCHIVING_CONFIG = ArchivingConfig()


class SearchBackendConfig(BaseConfigSet):
    USE_INDEXING_BACKEND: bool          = Field(default=True)
    USE_SEARCHING_BACKEND: bool         = Field(default=True)
    
    SEARCH_BACKEND_ENGINE: str          = Field(default='ripgrep')
    SEARCH_PROCESS_HTML: bool           = Field(default=True)
    SEARCH_BACKEND_TIMEOUT: int         = Field(default=10)

SEARCH_BACKEND_CONFIG = SearchBackendConfig()

