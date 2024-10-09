__package__ = 'archivebox.plugins_pkg.puppeteer'

import os
import platform
from pathlib import Path
from typing import List, Optional, Dict, ClassVar

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field
from pydantic_pkgr import (
    BinProvider,
    BinName,
    BinProviderName,
    ProviderLookupDict,
    InstallArgs,
    PATHStr,
    HostBinPath,
)

from archivebox.config import CONSTANTS
from archivebox.config.permissions import ARCHIVEBOX_USER

# Depends on other Django apps:
from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, BaseBinProvider, env
# from abx.archivebox.base_extractor import BaseExtractor
# from abx.archivebox.base_queue import BaseQueue
from abx.archivebox.base_hook import BaseHook

# Depends on Other Plugins:
from plugins_pkg.npm.apps import LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER


###################### Config ##########################


class PuppeteerConfigs(BaseConfigSet):
    # PUPPETEER_BINARY: str = Field(default='wget')
    # PUPPETEER_ARGS: Optional[List[str]] = Field(default=None)
    # PUPPETEER_EXTRA_ARGS: List[str] = []
    # PUPPETEER_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']
    pass


PUPPETEER_CONFIG = PuppeteerConfigs()

LIB_DIR_BROWSERS = CONSTANTS.LIB_BROWSERS_DIR


class PuppeteerBinary(BaseBinary):
    name: BinName = "puppeteer"

    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER, env]


PUPPETEER_BINARY = PuppeteerBinary()


class PuppeteerBinProvider(BaseBinProvider):
    name: BinProviderName = "puppeteer"
    INSTALLER_BIN: BinName = "npx"

    PATH: PATHStr = str(CONSTANTS.LIB_BIN_DIR)
    
    euid: Optional[int] = ARCHIVEBOX_USER

    puppeteer_browsers_dir: Optional[Path] = LIB_DIR_BROWSERS
    puppeteer_install_args: List[str] = ["@puppeteer/browsers", "install", "--path", str(LIB_DIR_BROWSERS)]

    packages_handler: ProviderLookupDict = Field(default={
        "chrome": lambda:
            ['chrome@stable'],
    }, exclude=True)
    
    _browser_abspaths: ClassVar[Dict[str, HostBinPath]] = {}
    
    def setup(self) -> None:
        assert SYS_NPM_BINPROVIDER.INSTALLER_BIN_ABSPATH, "NPM bin provider not initialized"
        
        if self.puppeteer_browsers_dir:
            self.puppeteer_browsers_dir.mkdir(parents=True, exist_ok=True)
    
    def installed_browser_bins(self, browser_name: str='*') -> List[Path]:
        # if on macOS, browser binary is inside a .app, otherwise it's just a plain binary
        if platform.system().lower() == 'darwin':
            # /data/lib/browsers/chrome/mac_arm-129.0.6668.58/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
            return sorted(self.puppeteer_browsers_dir.glob(f'{browser_name}/mac*/chrome*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'))

        # /data/lib/browsers/chrome/linux-131.0.6730.0/chrome-linux64/chrome
        return sorted(self.puppeteer_browsers_dir.glob(f"{browser_name}/linux*/chrome*/chrome"))

    def on_get_abspath(self, bin_name: BinName, **context) -> Optional[HostBinPath]:
        assert bin_name == 'chrome', 'Only chrome is supported using the @puppeteer/browsers install method currently.'
        
        # already loaded, return abspath from cache
        if bin_name in self._browser_abspaths:
            return self._browser_abspaths[bin_name]
        
        # first time loading, find browser in self.puppeteer_browsers_dir by searching filesystem for installed binaries
        matching_bins = [abspath for abspath in self.installed_browser_bins() if bin_name in str(abspath)]
        if matching_bins:
            newest_bin = matching_bins[-1]  # already sorted alphabetically, last should theoretically be highest version number
            self._browser_abspaths[bin_name] = newest_bin
            return self._browser_abspaths[bin_name]
        
        return None

    def on_install(self, bin_name: str, packages: Optional[InstallArgs] = None, **context) -> str:
        """npx @puppeteer/browsers install chrome@stable"""
        self.setup()
        assert bin_name == 'chrome', 'Only chrome is supported using the @puppeteer/browsers install method currently.'

        if not self.INSTALLER_BIN_ABSPATH:
            raise Exception(
                f"{self.__class__.__name__} install method is not available on this host ({self.INSTALLER_BIN} not found in $PATH)"
            )
        packages = packages or self.on_get_packages(bin_name)
        assert packages, f"No packages specified for installation of {bin_name}"

        # print(f'[*] {self.__class__.__name__}: Installing {bin_name}: {self.INSTALLER_BIN_ABSPATH} install {packages}')

        install_args = [*self.puppeteer_install_args]

        proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=[*install_args, *packages])

        if proc.returncode != 0:
            print(proc.stdout.strip())
            print(proc.stderr.strip())
            raise Exception(f"{self.__class__.__name__}: install got returncode {proc.returncode} while installing {packages}: {packages}")

        # to proceed? (y) chrome@129.0.6668.91 /tmp/test3/lib/x86_64-linux/browsers/chrome/linux-129.0.6668.91/chrome-linux64/chrome
        # chrome@129.0.6668.58 /data/lib/browsers/chrome/mac_arm-129.0.6668.58/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
        relpath = proc.stdout.strip().split(str(self.puppeteer_browsers_dir))[-1]
        abspath = self.puppeteer_browsers_dir / relpath
        
        if os.path.isfile(abspath) and os.access(abspath, os.X_OK):
            self._browser_abspaths[bin_name] = abspath
            return abspath

        return proc.stderr.strip() + "\n" + proc.stdout.strip()

PUPPETEER_BINPROVIDER = PuppeteerBinProvider()


# ALTERNATIVE INSTALL METHOD using Ansible:
# install_playbook = self.plugin_dir / 'install_puppeteer.yml'
# chrome_bin = run_playbook(install_playbook, data_dir=DATA_DIR, quiet=quiet).BINARIES.chrome
# return self.__class__.model_validate(
#     {
#         **self.model_dump(),
#         "loaded_abspath": chrome_bin.symlink,
#         "loaded_version": chrome_bin.version,
#         "loaded_binprovider": env,
#         "binproviders_supported": self.binproviders_supported,
#     }
# )


class PuppeteerPlugin(BasePlugin):
    app_label: str ='puppeteer'
    verbose_name: str = 'Puppeteer (NPM)'

    hooks: List[InstanceOf[BaseHook]] = [
        PUPPETEER_CONFIG,
        PUPPETEER_BINPROVIDER,
        PUPPETEER_BINARY,
    ]



PLUGIN = PuppeteerPlugin()
# PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
