__package__ = 'archivebox.plugins_pkg.pip'

import os
import sys
import inspect
import archivebox
from pathlib import Path
from typing import List, Dict, Optional, ClassVar
from pydantic import InstanceOf, Field, model_validator

import abx

import django
from django.db.backends.sqlite3.base import Database as django_sqlite3     # type: ignore[import-type]
from django.core.checks import Error, Tags

from pydantic_pkgr import BinProvider, PipProvider, BinName, BinProviderName, ProviderLookupDict, SemVer
from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet, ConfigSectionName
from abx.archivebox.base_check import BaseCheck
from abx.archivebox.base_binary import BaseBinary, BaseBinProvider, env, apt, brew
from abx.archivebox.base_hook import BaseHook

from ...misc.logging import hint


###################### Config ##########################


class PipDependencyConfigs(BaseConfigSet):
    section: ClassVar[ConfigSectionName] = "DEPENDENCY_CONFIG"

    USE_PIP: bool = True
    PIP_BINARY: str = Field(default='pip')
    PIP_ARGS: Optional[List[str]] = Field(default=None)
    PIP_EXTRA_ARGS: List[str] = []
    PIP_DEFAULT_ARGS: List[str] = []
    


DEFAULT_GLOBAL_CONFIG = {
}
PIP_CONFIG = PipDependencyConfigs(**DEFAULT_GLOBAL_CONFIG)

class SystemPipBinProvider(PipProvider, BaseBinProvider):
    name: BinProviderName = "sys_pip"
    INSTALLER_BIN: BinName = "pip"
    
    pip_venv: Optional[Path] = None        # global pip scope
    
    def on_install(self, bin_name: str, **kwargs):
        # never modify system pip packages
        return 'refusing to install packages globally with system pip, use a venv instead'

class SystemPipxBinProvider(PipProvider, BaseBinProvider):
    name: BinProviderName = "pipx"
    INSTALLER_BIN: BinName = "pipx"
    
    pip_venv: Optional[Path] = None        # global pipx scope


class VenvPipBinProvider(PipProvider, BaseBinProvider):
    name: BinProviderName = "venv_pip"
    INSTALLER_BIN: BinName = "pip"

    pip_venv: Optional[Path] = Path(os.environ.get("VIRTUAL_ENV", None) or '/tmp/NotInsideAVenv')


class LibPipBinProvider(PipProvider, BaseBinProvider):
    name: BinProviderName = "lib_pip"
    INSTALLER_BIN: BinName = "pip"
    
    pip_venv: Optional[Path] = archivebox.CONSTANTS.LIB_PIP_DIR / 'venv'

SYS_PIP_BINPROVIDER = SystemPipBinProvider()
PIPX_PIP_BINPROVIDER = SystemPipxBinProvider()
VENV_PIP_BINPROVIDER = VenvPipBinProvider()
LIB_PIP_BINPROVIDER = LibPipBinProvider()
pip = LIB_PIP_BINPROVIDER


class ArchiveboxBinary(BaseBinary):
    name: BinName = 'archivebox'

    binproviders_supported: List[InstanceOf[BinProvider]] = [VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, apt, brew, env]
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        VENV_PIP_BINPROVIDER.name:  {'packages': lambda: [], 'version': lambda: archivebox.__version__},
        SYS_PIP_BINPROVIDER.name:   {'packages': lambda: [], 'version': lambda: archivebox.__version__},
        apt.name:                   {'packages': lambda: [], 'version': lambda: archivebox.__version__},
        brew.name:                  {'packages': lambda: [], 'version': lambda: archivebox.__version__},
    }

ARCHIVEBOX_BINARY = ArchiveboxBinary()


class PythonBinary(BaseBinary):
    name: BinName = 'python'

    binproviders_supported: List[InstanceOf[BinProvider]] = [VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, apt, brew, env]
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        SYS_PIP_BINPROVIDER.name: {
            'abspath': lambda:
                sys.executable,
            'version': lambda: 
                '{}.{}.{}'.format(*sys.version_info[:3]),
        },
    }

PYTHON_BINARY = PythonBinary()

class SqliteBinary(BaseBinary):
    name: BinName = 'sqlite'
    binproviders_supported: List[InstanceOf[BaseBinProvider]] = Field(default=[VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER])
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        VENV_PIP_BINPROVIDER.name: {
            "abspath": lambda: Path(inspect.getfile(django_sqlite3)),
            "version": lambda: SemVer(django_sqlite3.version),
        },
        SYS_PIP_BINPROVIDER.name: {
            "abspath": lambda: Path(inspect.getfile(django_sqlite3)),
            "version": lambda: SemVer(django_sqlite3.version),
        },
    }
    
    @model_validator(mode='after')
    def validate_json_extension_is_available(self):
        # Check to make sure JSON extension is available in our Sqlite3 instance
        try:
            cursor = django_sqlite3.connect(':memory:').cursor()
            cursor.execute('SELECT JSON(\'{"a": "b"}\')')
        except django_sqlite3.OperationalError as exc:
            print(f'[red][X] Your SQLite3 version is missing the required JSON1 extension: {exc}[/red]')
            hint([
                'Upgrade your Python version or install the extension manually:',
                'https://code.djangoproject.com/wiki/JSON1Extension'
            ])
        return self

SQLITE_BINARY = SqliteBinary()


class DjangoBinary(BaseBinary):
    name: BinName = 'django'

    binproviders_supported: List[InstanceOf[BaseBinProvider]] = Field(default=[VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER])
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        VENV_PIP_BINPROVIDER.name: {
            "abspath": lambda: inspect.getfile(django),
            "version": lambda: django.VERSION[:3],
        },
        SYS_PIP_BINPROVIDER.name: {
            "abspath": lambda: inspect.getfile(django),
            "version": lambda: django.VERSION[:3],
        },
    }

DJANGO_BINARY = DjangoBinary()

class PipBinary(BaseBinary):
    name: BinName = "pip"
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, apt, brew, env]


PIP_BINARY = PipBinary()


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
        # logger.debug('[√] UID is not root')
        return errors

    
class CheckPipEnvironment(BaseCheck):
    label: str = "CheckPipEnvironment"
    tag: str = Tags.database

    @staticmethod
    def check(settings, logger) -> List[Warning]:
        # hard errors: check python version
        if sys.version_info[:3] < (3, 10, 0):
            print('[red][X] Python version is not new enough: {sys.version} (>3.10 is required)[/red]', file=sys.stderr)
            print('    See https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#python for help upgrading your Python installation.', file=sys.stderr)
            raise SystemExit(2)
        
        # hard errors: check django version
        if int(django.VERSION[0]) < 5:
            print('[red][X] Django version is not new enough: {django.VERSION[:3]} (>=5.0 is required)[/red]', file=sys.stderr)
            print('    Upgrade django using pip or your system package manager: pip3 install --upgrade django', file=sys.stderr)
            raise SystemExit(2)
        
        # soft errors: check that lib/pip virtualenv is setup properly
        errors = []
        
        LIB_PIP_BINPROVIDER.setup()
        if not LIB_PIP_BINPROVIDER.INSTALLER_BIN_ABSPATH:
            errors.append(
                Error(
                    "Failed to setup data/lib/pip virtualenv for runtime dependencies!",
                    id="pip.P001",
                    hint="Make sure the data dir is writable and make sure python3-pip and python3-venv are installed & available on the host.",
                )
            )
        # logger.debug("[√] CheckPipEnvironment: data/lib/pip virtualenv is setup properly")
        return errors


USER_IS_NOT_ROOT_CHECK = CheckUserIsNotRoot()
PIP_ENVIRONMENT_CHECK = CheckPipEnvironment()


class PipPlugin(BasePlugin):
    app_label: str = 'pip'
    verbose_name: str = 'PIP'

    hooks: List[InstanceOf[BaseHook]] = [
        PIP_CONFIG,
        SYS_PIP_BINPROVIDER,
        PIPX_PIP_BINPROVIDER,
        VENV_PIP_BINPROVIDER,
        LIB_PIP_BINPROVIDER,
        PIP_BINARY,
        ARCHIVEBOX_BINARY,
        PYTHON_BINARY,
        SQLITE_BINARY,
        DJANGO_BINARY,
        USER_IS_NOT_ROOT_CHECK,
        PIP_ENVIRONMENT_CHECK,
    ]

PLUGIN = PipPlugin()
# PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig


@abx.hookimpl
def register_django_checks(settings):
    USER_IS_NOT_ROOT_CHECK.register_with_django_check_system(settings)
    PIP_ENVIRONMENT_CHECK.register_with_django_check_system(settings)
