__package__ = 'archivebox.builtin_plugins.systempython'

import os
import sys
import inspect
from typing import List, Dict, Any, Callable, ClassVar
from pathlib import Path

import django
from django.apps import AppConfig
from django.core.checks import Tags, Warning, register
from django.utils.functional import classproperty
from django.db.backends.sqlite3.base import Database as sqlite3
from django.core.checks import Tags, Error, register

from pydantic import InstanceOf, Field

from pydantic_pkgr import SemVer, BinProvider, BinProviderName, ProviderLookupDict, BinName, Binary, EnvProvider, NpmProvider

from plugantic.base_plugin import BasePlugin, BaseConfigSet, BaseBinary, BaseBinProvider, BaseExtractor, BaseReplayer
from plugantic.base_check import BaseCheck

from pkg.settings import env, apt, brew

from builtin_plugins.pip.apps import pip

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


class BasicReplayer(BaseReplayer):
    name: str = 'basic'




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



class SystemPythonPlugin(BasePlugin):
    name: str = 'builtin_plugins.systempython'
    app_label: str = 'systempython'
    verbose_name: str = 'System Python'

    configs: List[InstanceOf[BaseConfigSet]] = []
    binaries: List[InstanceOf[BaseBinary]] = [PythonBinary(), SqliteBinary(), DjangoBinary()]
    extractors: List[InstanceOf[BaseExtractor]] = []
    replayers: List[InstanceOf[BaseReplayer]] = [BasicReplayer()]
    checks: List[InstanceOf[BaseCheck]] = [CheckUserIsNotRoot()]


PLUGIN = SystemPythonPlugin()
DJANGO_APP = PLUGIN.AppConfig
# CONFIGS = PLUGIN.configs
# BINARIES = PLUGIN.binaries
# EXTRACTORS = PLUGIN.extractors
# REPLAYERS = PLUGIN.replayers
# PARSERS = PLUGIN.parsers
# DAEMONS = PLUGIN.daemons
# MODELS = PLUGIN.models
# CHECKS = PLUGIN.checks
