__package__ = 'archivebox.config'

import sys
import shutil

from typing import Dict, Optional
from pathlib import Path

from rich import print
from pydantic import Field, field_validator, computed_field
from django.utils.crypto import get_random_string

from abx.archivebox.base_configset import BaseConfigSet


from .constants import CONSTANTS
from .version import get_COMMIT_HASH, get_BUILD_TIME
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

    VERSIONS_AVAILABLE: bool = False             # .check_for_update.get_versions_available_on_github(c)},
    CAN_UPGRADE: bool = False                    # .check_for_update.can_upgrade(c)},

    
    @computed_field
    @property
    def TERM_WIDTH(self) -> int:
        if not self.IS_TTY:
            return 200
        return shutil.get_terminal_size((140, 10)).columns
    
    @computed_field
    @property
    def COMMIT_HASH(self) -> Optional[str]:
        return get_COMMIT_HASH()
    
    @computed_field
    @property
    def BUILD_TIME(self) -> str:
        return get_BUILD_TIME()

SHELL_CONFIG = ShellConfig()


class StorageConfig(BaseConfigSet):
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
    PREVIEW_ORIGINALS: bool             = Field(default=True)
    
SERVER_CONFIG = ServerConfig()


class ArchivingConfig(BaseConfigSet):
    ONLY_NEW: bool                      = Field(default=True)
    
    TIMEOUT: int                        = Field(default=60)
    MEDIA_TIMEOUT: int                  = Field(default=3600)

    MEDIA_MAX_SIZE: str                 = Field(default='750m')
    RESOLUTION: str                     = Field(default='1440,2000')
    CHECK_SSL_VALIDITY: bool            = Field(default=True)
    USER_AGENT: str                     = Field(default='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 ArchiveBox/{VERSION} (+https://github.com/ArchiveBox/ArchiveBox/)')
    COOKIES_FILE: Path | None           = Field(default=None)
    
    URL_DENYLIST: str                   = Field(default=r'\.(css|js|otf|ttf|woff|woff2|gstatic\.com|googleapis\.com/css)(\?.*)?$', alias='URL_BLACKLIST')
    URL_ALLOWLIST: str | None           = Field(default=None, alias='URL_WHITELIST')
    
    # GIT_DOMAINS: str                    = Field(default='github.com,bitbucket.org,gitlab.com,gist.github.com,codeberg.org,gitea.com,git.sr.ht')
    # WGET_USER_AGENT: str                = Field(default=lambda c: c['USER_AGENT'] + ' wget/{WGET_VERSION}')
    # CURL_USER_AGENT: str                = Field(default=lambda c: c['USER_AGENT'] + ' curl/{CURL_VERSION}')
    # CHROME_USER_AGENT: str              = Field(default=lambda c: c['USER_AGENT'])
    # CHROME_USER_DATA_DIR: str | None    = Field(default=None)
    # CHROME_TIMEOUT: int                 = Field(default=0)
    # CHROME_HEADLESS: bool               = Field(default=True)
    # CHROME_SANDBOX: bool                = Field(default=lambda: not SHELL_CONFIG.IN_DOCKER)

    @field_validator('TIMEOUT', mode='after')
    def validate_timeout(cls, v):
        if int(v) < 5:
            print(f'[red][!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={v} seconds)[/red]', file=sys.stderr)
            print('    You must allow *at least* 5 seconds for indexing and archive methods to run succesfully.', file=sys.stderr)
            print('    (Setting it to somewhere between 30 and 3000 seconds is recommended)', file=sys.stderr)
            print(file=sys.stderr)
            print('    If you want to make ArchiveBox run faster, disable specific archive methods instead:', file=sys.stderr)
            print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#archive-method-toggles', file=sys.stderr)
            print(file=sys.stderr)
        return v
    
    @field_validator('CHECK_SSL_VALIDITY', mode='after')
    def validate_check_ssl_validity(cls, v):
        """SIDE EFFECT: disable "you really shouldnt disable ssl" warnings emitted by requests"""
        if not v:
            import requests
            import urllib3
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return v

ARCHIVING_CONFIG = ArchivingConfig()


class SearchBackendConfig(BaseConfigSet):
    USE_INDEXING_BACKEND: bool          = Field(default=True)
    USE_SEARCHING_BACKEND: bool         = Field(default=True)
    
    SEARCH_BACKEND_ENGINE: str          = Field(default='ripgrep')
    SEARCH_PROCESS_HTML: bool           = Field(default=True)
    SEARCH_BACKEND_TIMEOUT: int         = Field(default=10)

SEARCH_BACKEND_CONFIG = SearchBackendConfig()

