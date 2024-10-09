__package__ = 'archivebox.plugins_pkg.pip'

import os
import sys
import site
from pathlib import Path
from typing import List, Dict, Optional
from pydantic import InstanceOf, Field, model_validator, validate_call


import django
import django.db.backends.sqlite3.base
from django.db.backends.sqlite3.base import Database as django_sqlite3     # type: ignore[import-type]
from django.core.checks import Error, Tags
from pydantic_pkgr import BinProvider, PipProvider, BinName, BinProviderName, ProviderLookupDict, SemVer, bin_abspath

from archivebox.config import CONSTANTS, VERSION

from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_check import BaseCheck
from abx.archivebox.base_binary import BaseBinary, BaseBinProvider, env, apt, brew
from abx.archivebox.base_hook import BaseHook

from ...misc.logging import hint


###################### Config ##########################


class PipDependencyConfigs(BaseConfigSet):
    USE_PIP: bool = True
    PIP_BINARY: str = Field(default='pip')
    PIP_ARGS: Optional[List[str]] = Field(default=None)
    PIP_EXTRA_ARGS: List[str] = []
    PIP_DEFAULT_ARGS: List[str] = []
    
PIP_CONFIG = PipDependencyConfigs()


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


IS_INSIDE_VENV = sys.prefix != sys.base_prefix

class VenvPipBinProvider(PipProvider, BaseBinProvider):
    name: BinProviderName = "venv_pip"
    INSTALLER_BIN: BinName = "pip"

    pip_venv: Optional[Path] = Path(sys.prefix if IS_INSIDE_VENV else os.environ.get("VIRTUAL_ENV", '/tmp/NotInsideAVenv/lib'))
    
    def setup(self):
        """never attempt to create a venv here, this is just used to detect if we are inside an existing one"""
        return None
    

class LibPipBinProvider(PipProvider, BaseBinProvider):
    name: BinProviderName = "lib_pip"
    INSTALLER_BIN: BinName = "pip"
    
    pip_venv: Optional[Path] = CONSTANTS.LIB_PIP_DIR / 'venv'

SYS_PIP_BINPROVIDER = SystemPipBinProvider()
PIPX_PIP_BINPROVIDER = SystemPipxBinProvider()
VENV_PIP_BINPROVIDER = VenvPipBinProvider()
LIB_PIP_BINPROVIDER = LibPipBinProvider()
pip = LIB_PIP_BINPROVIDER

# ensure python libraries are importable from these locations (if archivebox wasnt executed from one of these then they wont already be in sys.path)
assert VENV_PIP_BINPROVIDER.pip_venv is not None
assert LIB_PIP_BINPROVIDER.pip_venv is not None

major, minor, patch = sys.version_info[:3]
site_packages_dir = f'lib/python{major}.{minor}/site-packages'

LIB_SITE_PACKAGES = (LIB_PIP_BINPROVIDER.pip_venv / site_packages_dir,)
VENV_SITE_PACKAGES = (VENV_PIP_BINPROVIDER.pip_venv / site_packages_dir,)
USER_SITE_PACKAGES = site.getusersitepackages()
SYS_SITE_PACKAGES = site.getsitepackages()

ALL_SITE_PACKAGES = (
    *LIB_SITE_PACKAGES,
    *VENV_SITE_PACKAGES,
    *USER_SITE_PACKAGES,
    *SYS_SITE_PACKAGES,
)
for site_packages_dir in ALL_SITE_PACKAGES:
    if site_packages_dir not in sys.path:
        sys.path.append(str(site_packages_dir))


class ArchiveboxBinary(BaseBinary):
    name: BinName = 'archivebox'

    binproviders_supported: List[InstanceOf[BinProvider]] = [VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, apt, brew, env]
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        VENV_PIP_BINPROVIDER.name:  {'packages': lambda: [], 'version': lambda: VERSION},
        SYS_PIP_BINPROVIDER.name:   {'packages': lambda: [], 'version': lambda: VERSION},
        apt.name:                   {'packages': lambda: [], 'version': lambda: VERSION},
        brew.name:                  {'packages': lambda: [], 'version': lambda: VERSION},
    }
    
    @validate_call
    def install(self, **kwargs):
        return self.load()                  # obviously it's already installed if we are running this ;)
    
    @validate_call
    def load_or_install(self, **kwargs):
        return self.load()                  # obviously it's already installed if we are running this ;)

ARCHIVEBOX_BINARY = ArchiveboxBinary()


class PythonBinary(BaseBinary):
    name: BinName = 'python'

    binproviders_supported: List[InstanceOf[BinProvider]] = [VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, apt, brew, env]
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        SYS_PIP_BINPROVIDER.name: {
            'abspath': lambda: sys.executable,
            'version': lambda: '{}.{}.{}'.format(*sys.version_info[:3]),
        },
    }
    
    @validate_call
    def install(self, **kwargs):
        return self.load()                  # obviously it's already installed if we are running this ;)
    
    @validate_call
    def load_or_install(self, **kwargs):
        return self.load()                  # obviously it's already installed if we are running this ;)

PYTHON_BINARY = PythonBinary()


LOADED_SQLITE_PATH = Path(django.db.backends.sqlite3.base.__file__)
LOADED_SQLITE_VERSION = SemVer(django_sqlite3.version)
LOADED_SQLITE_FROM_VENV = str(LOADED_SQLITE_PATH.absolute().resolve()).startswith(str(VENV_PIP_BINPROVIDER.pip_venv.absolute().resolve()))

class SqliteBinary(BaseBinary):
    name: BinName = 'sqlite'
    binproviders_supported: List[InstanceOf[BaseBinProvider]] = Field(default=[VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER])
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        VENV_PIP_BINPROVIDER.name: {
            "abspath": lambda: LOADED_SQLITE_PATH if LOADED_SQLITE_FROM_VENV else None,
            "version": lambda: LOADED_SQLITE_VERSION if LOADED_SQLITE_FROM_VENV else None,
        },
        SYS_PIP_BINPROVIDER.name: {
            "abspath": lambda: LOADED_SQLITE_PATH if not LOADED_SQLITE_FROM_VENV else None,
            "version": lambda: LOADED_SQLITE_VERSION if not LOADED_SQLITE_FROM_VENV else None,
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
    
    @validate_call
    def install(self, **kwargs):
        return self.load()                  # obviously it's already installed if we are running this ;)
    
    @validate_call
    def load_or_install(self, **kwargs):
        return self.load()                  # obviously it's already installed if we are running this ;)

SQLITE_BINARY = SqliteBinary()


LOADED_DJANGO_PATH = Path(django.__file__)
LOADED_DJANGO_VERSION = SemVer(django.VERSION[:3])
LOADED_DJANGO_FROM_VENV = str(LOADED_DJANGO_PATH.absolute().resolve()).startswith(str(VENV_PIP_BINPROVIDER.pip_venv.absolute().resolve()))

class DjangoBinary(BaseBinary):
    name: BinName = 'django'

    binproviders_supported: List[InstanceOf[BaseBinProvider]] = Field(default=[VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER])
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        VENV_PIP_BINPROVIDER.name: {
            "abspath": lambda: LOADED_DJANGO_PATH if LOADED_DJANGO_FROM_VENV else None,
            "version": lambda: LOADED_DJANGO_VERSION if LOADED_DJANGO_FROM_VENV else None,
        },
        SYS_PIP_BINPROVIDER.name: {
            "abspath": lambda: LOADED_DJANGO_PATH if not LOADED_DJANGO_FROM_VENV else None,
            "version": lambda: LOADED_DJANGO_VERSION if not LOADED_DJANGO_FROM_VENV else None,
        },
    }
    
    @validate_call
    def install(self, **kwargs):
        return self.load()                  # obviously it's already installed if we are running this ;)
    
    @validate_call
    def load_or_install(self, **kwargs):
        return self.load()                  # obviously it's already installed if we are running this ;)

DJANGO_BINARY = DjangoBinary()

class PipBinary(BaseBinary):
    name: BinName = "pip"
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, apt, brew, env]

    @validate_call
    def install(self, **kwargs):
        return self.load()                  # obviously it's already installed if we are running this ;)
    
    @validate_call
    def load_or_install(self, **kwargs):
        return self.load()                  # obviously it's already installed if we are running this ;)

PIP_BINARY = PipBinary()


class PipxBinary(BaseBinary):
    name: BinName = "pipx"
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, apt, brew, env]

PIPX_BINARY = PipxBinary()


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
        # soft errors: check that lib/pip virtualenv is setup properly
        errors = []
        
        LIB_PIP_BINPROVIDER.setup()
        if not LIB_PIP_BINPROVIDER.is_valid:
            errors.append(
                Error(
                    f"Failed to setup {LIB_PIP_BINPROVIDER.pip_venv} virtualenv for runtime dependencies!",
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
        PIPX_BINARY,
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
