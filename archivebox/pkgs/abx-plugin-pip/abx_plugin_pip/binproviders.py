import os
import sys
import site
from pathlib import Path
from typing import Optional

from benedict import benedict

from abx_pkg import PipProvider, BinName, BinProviderName

import abx

from abx_plugin_default_binproviders import get_BINPROVIDERS

DEFAULT_BINPROVIDERS = benedict(get_BINPROVIDERS())
env = DEFAULT_BINPROVIDERS.env
apt = DEFAULT_BINPROVIDERS.apt
brew = DEFAULT_BINPROVIDERS.brew


###################### Config ##########################

class SystemPipBinProvider(PipProvider):
    name: BinProviderName = "sys_pip"
    INSTALLER_BIN: BinName = "pip"
    
    pip_venv: Optional[Path] = None        # global pip scope
    
    def on_install(self, bin_name: str, **kwargs):
        # never modify system pip packages
        return 'refusing to install packages globally with system pip, use a venv instead'

class SystemPipxBinProvider(PipProvider):
    name: BinProviderName = "pipx"
    INSTALLER_BIN: BinName = "pipx"
    
    pip_venv: Optional[Path] = None        # global pipx scope


IS_INSIDE_VENV = sys.prefix != sys.base_prefix

class VenvPipBinProvider(PipProvider):
    name: BinProviderName = "venv_pip"
    INSTALLER_BIN: BinName = "pip"

    pip_venv: Optional[Path] = Path(sys.prefix if IS_INSIDE_VENV else os.environ.get("VIRTUAL_ENV", '/tmp/NotInsideAVenv/lib'))
    
    def setup(self):
        """never attempt to create a venv here, this is just used to detect if we are inside an existing one"""
        return None
    

class LibPipBinProvider(PipProvider):
    name: BinProviderName = "lib_pip"
    INSTALLER_BIN: BinName = "pip"
    
    pip_venv: Optional[Path] = Path('/usr/local/share/abx/pip/venv')
    
    def setup(self) -> None:
        # update venv path to match most up-to-date LIB_DIR based on runtime config
        LIB_DIR = abx.pm.hook.get_LIB_DIR()
        self.pip_venv = LIB_DIR / 'pip' / 'venv'
        super().setup()

SYS_PIP_BINPROVIDER = SystemPipBinProvider()
SYS_PIP_BINPROVIDER.setup()
PIPX_PIP_BINPROVIDER = SystemPipxBinProvider()
PIPX_PIP_BINPROVIDER.setup()
VENV_PIP_BINPROVIDER = VenvPipBinProvider()
VENV_PIP_BINPROVIDER.setup()
LIB_PIP_BINPROVIDER = LibPipBinProvider()
LIB_PIP_BINPROVIDER.setup()
pip = LIB_PIP_BINPROVIDER

SYS_PIP_BINPROVIDER.setup()
PIPX_PIP_BINPROVIDER.setup()
VENV_PIP_BINPROVIDER.setup()
LIB_PIP_BINPROVIDER.setup()

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
