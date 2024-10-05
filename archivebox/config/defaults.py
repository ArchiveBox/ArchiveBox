__package__ = 'archivebox.config'

import os
import sys
import shutil

from typing import Dict, Optional
from datetime import datetime
from pathlib import Path

from rich import print
from pydantic import Field, field_validator, model_validator, computed_field
from django.utils.crypto import get_random_string

from abx.archivebox.base_configset import BaseConfigSet


from .constants import CONSTANTS, PACKAGE_DIR

###################### Config ##########################


class ShellConfig(BaseConfigSet):
    DEBUG: bool                         = Field(default=lambda: '--debug' in sys.argv)
    
    IS_TTY: bool                        = Field(default=sys.stdout.isatty())
    USE_COLOR: bool                     = Field(default=lambda c: c.IS_TTY)
    SHOW_PROGRESS: bool                 = Field(default=lambda c: c.IS_TTY)
    
    IN_DOCKER: bool                     = Field(default=False)
    IN_QEMU: bool                       = Field(default=False)
    
    USER: str                           = Field(default=Path('~').expanduser().resolve().name)
    PUID: int                           = Field(default=os.getuid())
    PGID: int                           = Field(default=os.getgid())
    
    PYTHON_ENCODING: str                = Field(default=(sys.__stdout__ or sys.stdout or sys.__stderr__ or sys.stderr).encoding.upper().replace('UTF8', 'UTF-8'))

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
        try:
            git_dir = PACKAGE_DIR / '../.git'
            ref = (git_dir / 'HEAD').read_text().strip().split(' ')[-1]
            commit_hash = git_dir.joinpath(ref).read_text().strip()
            return commit_hash
        except Exception:
            pass
    
        try:
            return list((PACKAGE_DIR / '../.git/refs/heads/').glob('*'))[0].read_text().strip()
        except Exception:
            pass
        
        return None
    
    @computed_field
    @property
    def BUILD_TIME(self) -> str:
        if self.IN_DOCKER:
            docker_build_end_time = Path('/VERSION.txt').read_text().rsplit('BUILD_END_TIME=')[-1].split('\n', 1)[0]
            return docker_build_end_time
    
        src_last_modified_unix_timestamp = (PACKAGE_DIR / 'README.md').stat().st_mtime
        return datetime.fromtimestamp(src_last_modified_unix_timestamp).strftime('%Y-%m-%d %H:%M:%S %s')
    

    @model_validator(mode='after')
    def validate_not_running_as_root(self):
        attempted_command = ' '.join(sys.argv[:3])
        if self.PUID == 0 and attempted_command not in ('setup', 'install'):
            # stderr('[!] ArchiveBox should never be run as root!', color='red')
            # stderr('    For more information, see the security overview documentation:')
            # stderr('        https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#do-not-run-as-root')
            print('[red][!] ArchiveBox should never be run as root![/red]', file=sys.stderr)
            print('    For more information, see the security overview documentation:', file=sys.stderr)
            print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#do-not-run-as-root', file=sys.stderr)
            
            if self.IN_DOCKER:
                print('[red][!] When using Docker, you must run commands with [green]docker run[/green] instead of [yellow3]docker exec[/yellow3], e.g.:', file=sys.stderr)
                print('        docker compose run archivebox {attempted_command}', file=sys.stderr)
                print(f'        docker run -it -v $PWD/data:/data archivebox/archivebox {attempted_command}', file=sys.stderr)
                print('        or:', file=sys.stderr)
                print(f'        docker compose exec --user=archivebox archivebox /bin/bash -c "archivebox {attempted_command}"', file=sys.stderr)
                print(f'        docker exec -it --user=archivebox <container id> /bin/bash -c "archivebox {attempted_command}"', file=sys.stderr)
            raise SystemExit(2)
        
        # check python locale
        if self.PYTHON_ENCODING != 'UTF-8':
            print(f'[red][X] Your system is running python3 scripts with a bad locale setting: {self.PYTHON_ENCODING} (it should be UTF-8).[/red]', file=sys.stderr)
            print('    To fix it, add the line "export PYTHONIOENCODING=UTF-8" to your ~/.bashrc file (without quotes)', file=sys.stderr)
            print('    Or if you\'re using ubuntu/debian, run "dpkg-reconfigure locales"', file=sys.stderr)
            print('')
            print('    Confirm that it\'s fixed by opening a new shell and running:', file=sys.stderr)
            print('        python3 -c "import sys; print(sys.stdout.encoding)"   # should output UTF-8', file=sys.stderr)
            raise SystemExit(2)
        
        return self

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

