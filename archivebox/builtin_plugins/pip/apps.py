import os
import sys
import inspect
from pathlib import Path
from typing import List, Dict, Optional
from pydantic import InstanceOf, Field

import django
from django.apps import AppConfig

from django.db.backends.sqlite3.base import Database as sqlite3
from django.core.checks import Error, Tags, register

from pydantic_pkgr import BinProvider, PipProvider, BinName, PATHStr, BinProviderName, ProviderLookupDict, SemVer
from plugantic.base_plugin import BasePlugin, BaseConfigSet, BaseBinary, BaseBinProvider
from plugantic.base_configset import ConfigSectionName
from plugantic.base_check import BaseCheck

from pkg.settings import env, apt, brew


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

class PipProvider(PipProvider, BaseBinProvider):
    PATH: PATHStr = str(Path(sys.executable).parent)

pip = PipProvider(PATH=str(Path(sys.executable).parent))


class PipBinary(BaseBinary):
    name: BinName = 'pip'
    binproviders_supported: List[InstanceOf[BinProvider]] = [pip, apt, brew, env]
PIP_BINARY = PipBinary()





class PythonBinary(BaseBinary):
    name: BinName = 'python'

    binproviders_supported: List[InstanceOf[BinProvider]] = [pip, apt, brew, env]
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        'apt': {
            'subdeps': \
                lambda: 'python3 python3-minimal python3-pip python3-virtualenv',
            'abspath': \
                lambda: sys.executable,
            'version': \
                lambda: '{}.{}.{}'.format(*sys.version_info[:3]),
        },
    }

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




class CheckUserIsNotRoot(BaseCheck):
    label: str = 'CheckUserIsNotRoot'
    tag = Tags.database

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




class PipPlugin(BasePlugin):
    name: str = 'builtin_plugins.pip'
    app_label: str = 'pip'
    verbose_name: str = 'PIP'

    configs: List[InstanceOf[BaseConfigSet]] = [PIP_CONFIG]
    binproviders: List[InstanceOf[BaseBinProvider]] = [pip]
    binaries: List[InstanceOf[BaseBinary]] = [PIP_BINARY, PythonBinary(), SqliteBinary(), DjangoBinary()]
    checks: List[InstanceOf[BaseCheck]] = [CheckUserIsNotRoot()]


PLUGIN = PipPlugin()
DJANGO_APP = PLUGIN.AppConfig
# CONFIGS = PLUGIN.configs
# BINARIES = PLUGIN.binaries
# EXTRACTORS = PLUGIN.extractors
# REPLAYERS = PLUGIN.replayers
# CHECKS = PLUGIN.checks
