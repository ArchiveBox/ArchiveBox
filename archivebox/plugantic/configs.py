__package__ = 'archivebox.plugantic'


from typing import Optional, List, Literal
from pathlib import Path
from pydantic import BaseModel, Field


ConfigSectionName = Literal['GENERAL_CONFIG', 'ARCHIVE_METHOD_TOGGLES', 'ARCHIVE_METHOD_OPTIONS', 'DEPENDENCY_CONFIG']


class ConfigSet(BaseModel):
    section: ConfigSectionName = 'GENERAL_CONFIG'

class WgetToggleConfig(ConfigSet):
    section: ConfigSectionName = 'ARCHIVE_METHOD_TOGGLES'

    SAVE_WGET: bool = True
    SAVE_WARC: bool = True

class WgetDependencyConfig(ConfigSet):
    section: ConfigSectionName = 'DEPENDENCY_CONFIG'

    WGET_BINARY: str = Field(default='wget')
    WGET_ARGS: Optional[List[str]] = Field(default=None)
    WGET_EXTRA_ARGS: List[str] = []
    WGET_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']

class WgetOptionsConfig(ConfigSet):
    section: ConfigSectionName = 'ARCHIVE_METHOD_OPTIONS'

    # loaded from shared config
    WGET_AUTO_COMPRESSION: bool = Field(default=True)
    SAVE_WGET_REQUISITES: bool = Field(default=True)
    WGET_USER_AGENT: str = Field(default='', alias='USER_AGENT')
    WGET_TIMEOUT: int = Field(default=60, alias='TIMEOUT')
    WGET_CHECK_SSL_VALIDITY: bool = Field(default=True, alias='CHECK_SSL_VALIDITY')
    WGET_RESTRICT_FILE_NAMES: str = Field(default='windows', alias='RESTRICT_FILE_NAMES')
    WGET_COOKIES_FILE: Optional[Path] = Field(default=None, alias='COOKIES_FILE')


CONFIG = {
    'CHECK_SSL_VALIDITY': False,
    'SAVE_WARC': False,
    'TIMEOUT': 999,
}


WGET_CONFIG = [
    WgetToggleConfig(**CONFIG),
    WgetDependencyConfig(**CONFIG),
    WgetOptionsConfig(**CONFIG),
]
