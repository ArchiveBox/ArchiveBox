import os
import sys
import inspect
from pathlib import Path
from typing import List, Dict, Optional
from pydantic import InstanceOf, Field

import django

from django.db.backends.sqlite3.base import Database as sqlite3     # type: ignore[import-type]
from django.core.checks import Error, Tags
from django.conf import settings

from pydantic_pkgr import BinProvider, PipProvider, BinName, PATHStr, BinProviderName, ProviderLookupDict, SemVer
from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet, ConfigSectionName
from plugantic.base_check import BaseCheck
from plugantic.base_binary import BaseBinary, BaseBinProvider, env, apt, brew
from plugantic.base_hook import BaseHook


###################### Config ##########################


class PipDependencyConfigs(BaseConfigSet):
    section: ConfigSectionName = 'DEPENDENCY_CONFIG'

    USE_PIP: bool = True
    PIP_BINARY: str = Field(default='pip')
    PIP_ARGS: Optional[List[str]] = Field(default=None)
    PIP_EXTRA_ARGS: List[str] = []
    PIP_DEFAULT_ARGS: List[str] = []


DEFAULT_GLOBAL_CONFIG = {
}
PIP_CONFIG = PipDependencyConfigs(**DEFAULT_GLOBAL_CONFIG)

class CustomPipProvider(PipProvider, BaseBinProvider):
    name: str = 'pip'
    INSTALLER_BIN: str = 'pip'
    PATH: PATHStr = str(Path(sys.executable).parent)


PIP_BINPROVIDER = CustomPipProvider(PATH=str(Path(sys.executable).parent))
pip = PIP_BINPROVIDER

class PipBinary(BaseBinary):
    name: BinName = 'pip'
    binproviders_supported: List[InstanceOf[BinProvider]] = [pip, apt, brew, env]

PIP_BINARY = PipBinary()





class PythonBinary(BaseBinary):
    name: BinName = 'python'

    binproviders_supported: List[InstanceOf[BinProvider]] = [pip, apt, brew, env]
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        'apt': {
            'packages': \
                lambda: 'python3 python3-minimal python3-pip python3-setuptools python3-virtualenv',
            'abspath': \
                lambda: sys.executable,
            'version': \
                lambda: '{}.{}.{}'.format(*sys.version_info[:3]),
        },
    }

PYTHON_BINARY = PythonBinary()

class SqliteBinary(BaseBinary):
    name: BinName = 'sqlite'
    binproviders_supported: List[InstanceOf[BaseBinProvider]] = Field(default=[pip])
    provider_overrides:  Dict[BinProviderName, ProviderLookupDict] = {
        'pip': {
            'abspath': \
                lambda: Path(inspect.getfile(sqlite3)),
            'version': \
                lambda: SemVer(sqlite3.version),
        },
    }

SQLITE_BINARY = SqliteBinary()


class DjangoBinary(BaseBinary):
    name: BinName = 'django'

    binproviders_supported: List[InstanceOf[BaseBinProvider]] = Field(default=[pip])
    provider_overrides:  Dict[BinProviderName, ProviderLookupDict] = {
        'pip': {
            'abspath': \
                lambda: inspect.getfile(django),
            'version': \
                lambda: django.VERSION[:3],
        },
    }

DJANGO_BINARY = DjangoBinary()


class CheckUserIsNotRoot(BaseCheck):
    label: str = 'CheckUserIsNotRoot'
    tag: str = Tags.database

    @staticmethod
    def check(settings, logger) -> List[Warning]:
        errors = []
        if getattr(settings, "USER", None) == 'root' or getattr(settings, "PUID", None) == 0:
            errors.append(
                Error(
                    "Cannot run as root!",
                    id="core.S001",
                    hint=f'Run ArchiveBox as a non-root user with a UID greater than 500. (currently running as UID {os.getuid()}).',
                )
            )
        logger.debug('[√] UID is not root')
        return errors


USER_IS_NOT_ROOT_CHECK = CheckUserIsNotRoot()


class PipPlugin(BasePlugin):
    app_label: str = 'pip'
    verbose_name: str = 'PIP'

    hooks: List[InstanceOf[BaseHook]] = [
        PIP_CONFIG,
        PIP_BINPROVIDER,
        PIP_BINARY,
        PYTHON_BINARY,
        SQLITE_BINARY,
        DJANGO_BINARY,
        USER_IS_NOT_ROOT_CHECK,
    ]

PLUGIN = PipPlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
