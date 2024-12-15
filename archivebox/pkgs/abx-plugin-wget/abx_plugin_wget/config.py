import subprocess
from typing import List, Optional
from pathlib import Path

from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet

from archivebox.config.common import ARCHIVING_CONFIG, STORAGE_CONFIG
from archivebox.misc.logging import STDERR


class WgetConfig(BaseConfigSet):

    SAVE_WGET: bool = True
    SAVE_WARC: bool = True
    
    USE_WGET: bool = Field(default=lambda c: c.SAVE_WGET or c.SAVE_WARC)
    
    WGET_BINARY: str = Field(default='wget')
    WGET_ARGS: List[str] = [
        '--no-verbose',
        '--adjust-extension',
        '--convert-links',
        '--force-directories',
        '--backup-converted',
        '--span-hosts',
        '--no-parent',
        '-e', 'robots=off',
    ]
    WGET_EXTRA_ARGS: List[str] = []
    
    SAVE_WGET_REQUISITES: bool = Field(default=True)
    WGET_RESTRICT_FILE_NAMES: str = Field(default=lambda: STORAGE_CONFIG.RESTRICT_FILE_NAMES)
    
    WGET_TIMEOUT: int =  Field(default=lambda: ARCHIVING_CONFIG.TIMEOUT)
    WGET_CHECK_SSL_VALIDITY: bool = Field(default=lambda: ARCHIVING_CONFIG.CHECK_SSL_VALIDITY)
    WGET_USER_AGENT: str = Field(default=lambda: ARCHIVING_CONFIG.USER_AGENT)
    WGET_COOKIES_FILE: Optional[Path] = Field(default=lambda: ARCHIVING_CONFIG.COOKIES_FILE)
    
    def validate(self):
        if self.USE_WGET and self.WGET_TIMEOUT < 10:
            STDERR.print(f'[red][!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={self.WGET_TIMEOUT} seconds)[/red]')
            STDERR.print('    wget will fail to archive any sites if set to less than ~20 seconds.')
            STDERR.print('    (Setting it somewhere over 60 seconds is recommended)')
            STDERR.print()
            STDERR.print('    If you want to disable media archiving entirely, set SAVE_MEDIA=False instead:')
            STDERR.print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#save_media')
            STDERR.print()
        return self

    @property
    def WGET_AUTO_COMPRESSION(self) -> bool:
        if hasattr(self, '_WGET_AUTO_COMPRESSION'):
            return self._WGET_AUTO_COMPRESSION
        try:
            cmd = [
                self.WGET_BINARY,
                "--compression=auto",
                "--help",
            ]
            self._WGET_AUTO_COMPRESSION = not subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3).returncode
            return self._WGET_AUTO_COMPRESSION
        except (FileNotFoundError, OSError):
            self._WGET_AUTO_COMPRESSION = False
            return False

WGET_CONFIG = WgetConfig()

