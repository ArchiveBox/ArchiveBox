import platform
from pathlib import Path
from typing import List, Optional, Dict, ClassVar

from django.conf import settings

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field
from pydantic_pkgr import BinProvider, BinName, BinProviderName, ProviderLookupDict, InstallArgs, HostBinPath, bin_abspath

# Depends on other Django apps:
from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet, ConfigSectionName
from plugantic.base_binary import BaseBinary, BaseBinProvider, env
# from plugantic.base_extractor import BaseExtractor
# from plugantic.base_queue import BaseQueue
from plugantic.base_hook import BaseHook

# Depends on Other Plugins:
from builtin_plugins.npm.apps import SYS_NPM_BINPROVIDER


###################### Config ##########################


class PuppeteerDependencyConfigs(BaseConfigSet):
    section: ConfigSectionName = 'DEPENDENCY_CONFIG'

    PUPPETEER_BINARY: str = Field(default='wget')
    PUPPETEER_ARGS: Optional[List[str]] = Field(default=None)
    PUPPETEER_EXTRA_ARGS: List[str] = []
    PUPPETEER_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']

class PuppeteerConfigs(PuppeteerDependencyConfigs):
    # section: ConfigSectionName = 'ALL_CONFIGS'
    pass

DEFAULT_GLOBAL_CONFIG = {
}

PUPPETEER_CONFIG = PuppeteerConfigs(**DEFAULT_GLOBAL_CONFIG)

LIB_DIR_BROWSERS = settings.CONFIG.OUTPUT_DIR / "lib" / "browsers"

class PuppeteerBinProvider(BaseBinProvider):
    name: BinProviderName = "puppeteer"
    INSTALLER_BIN: BinName = "npx"

    puppeteer_browsers_dir: Optional[Path] = LIB_DIR_BROWSERS
    puppeteer_install_args: List[str] = ["@puppeteer/browsers", "install", "--path", str(LIB_DIR_BROWSERS)]

    # packages_handler: ProviderLookupDict = {
    #     "chrome": lambda:
    #         ['chrome@stable'],
    # }
    
    _browser_abspaths: ClassVar[Dict[str, HostBinPath]] = {}
    
    def setup(self) -> None:
        assert SYS_NPM_BINPROVIDER.INSTALLER_BIN_ABSPATH, "NPM bin provider not initialized"
        
        if self.puppeteer_browsers_dir:
            self.puppeteer_browsers_dir.mkdir(parents=True, exist_ok=True)

    def on_get_abspath(self, bin_name: BinName, **context) -> Optional[HostBinPath]:
        assert bin_name == 'chrome', 'Only chrome is supported using the @puppeteer/browsers install method currently.'
        
        # already loaded, return abspath from cache
        if bin_name in self._browser_abspaths:
            return self._browser_abspaths[bin_name]
        
        # first time loading, find browser in self.puppeteer_browsers_dir by searching filesystem for installed binaries
        browsers_present = [d.name for d in self.puppeteer_browsers_dir.glob("*")]
        if bin_name in browsers_present:
            candidates = []
            # if on macOS, browser binary is inside a .app, otherwise it's just a plain binary
            if platform.system().lower() == 'darwin':
                # /data/lib/browsers/chrome/mac_arm-129.0.6668.58/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
                candidates = sorted(self.puppeteer_browsers_dir.glob(f'/{bin_name}/mac*/chrome*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'))
            else:
                # /data/lib/browsers/chrome/linux-131.0.6730.0/chrome-linux64/chrome
                candidates = sorted(self.puppeteer_browsers_dir.glob(f'/{bin_name}/linux*/chrome*/chrome'))
            if candidates:
                self._browser_abspaths[bin_name] = candidates[-1]
                return self._browser_abspaths[bin_name]
        
        return super().on_get_abspath(bin_name, **context)

    def on_install(self, bin_name: str, packages: Optional[InstallArgs] = None, **context) -> str:
        """npx @puppeteer/browsers install chrome@stable"""
        self.setup()
        assert bin_name == 'chrome', 'Only chrome is supported using the @puppeteer/browsers install method currently.'

        if not self.INSTALLER_BIN_ABSPATH:
            raise Exception(
                f"{self.__class__.__name__} install method is not available on this host ({self.INSTALLER_BIN} not found in $PATH)"
            )
        packages = packages or self.on_get_packages(bin_name)

        # print(f'[*] {self.__class__.__name__}: Installing {bin_name}: {self.INSTALLER_BIN_ABSPATH} install {packages}')

        install_args = [*self.puppeteer_install_args]

        proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=[*install_args, *packages])

        if proc.returncode != 0:
            print(proc.stdout.strip())
            print(proc.stderr.strip())
            raise Exception(f"{self.__class__.__name__}: install got returncode {proc.returncode} while installing {packages}: {packages}")

        # chrome@129.0.6668.58 /data/lib/browsers/chrome/mac_arm-129.0.6668.58/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
        output_info = proc.stdout.strip().split('\n')[-1]
        browser_abspath = output_info.split(' ', 1)[-1]
        # browser_version = output_info.split('@', 1)[-1].split(' ', 1)[0]
        
        self._browser_abspaths[bin_name] = Path(browser_abspath)

        return proc.stderr.strip() + "\n" + proc.stdout.strip()

PUPPETEER_BINPROVIDER = PuppeteerBinProvider()

CHROMIUM_BINARY_NAMES = [
    'chromium',
    'chromium-browser',
    'chromium-browser-beta',
    'chromium-browser-unstable',
    'chromium-browser-canary',
    'chromium-browser-dev'   
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
]
CHROME_BINARY_NAMES = [
    'google-chrome',
    'google-chrome-stable',
    'google-chrome-beta',
    'google-chrome-canary',
    'google-chrome-unstable',
    'google-chrome-dev',
    # 'chrome',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
]

def autodetect_system_chrome_install(PATH=None):
    for bin_name in CHROME_BINARY_NAMES + CHROMIUM_BINARY_NAMES:
        abspath = bin_abspath(bin_name, PATH=env.PATH)
        if abspath:
            return abspath
    return None

class ChromeBinary(BaseBinary):
    name: BinName = 'chrome'
    binproviders_supported: List[InstanceOf[BinProvider]] = [PUPPETEER_BINPROVIDER, env]
    
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        env.name: {
            'abspath': lambda:
                autodetect_system_chrome_install(PATH=env.PATH),
        },
        PUPPETEER_BINPROVIDER.name: {
            'packages': lambda:
                ['chrome@stable'],
        }
    }

    @staticmethod
    def symlink_to_lib(binary, bin_dir=settings.CONFIG.BIN_DIR) -> None:
        if not (binary.abspath and binary.abspath.exists()):
            return
        bin_dir.mkdir(parents=True, exist_ok=True)
        symlink = bin_dir / binary.name
        
        if platform.system().lower() == 'darwin':
            # if on macOS, browser binary is inside a .app, so we need to create a tiny bash script instead of a symlink
            symlink.write_text(f"""#!/usr/bin/env bash\nexec '{binary.abspath}' "$@"\n""")
            symlink.chmod(0o777)   # make sure its executable by everyone
        else:
            # otherwise on linux we can symlink directly to binary executable
            symlink.symlink_to(binary.abspath)


# ALTERNATIVE INSTALL METHOD using Ansible:
# install_playbook = self.plugin_dir / 'install_puppeteer.yml'
# chrome_bin = run_playbook(install_playbook, data_dir=settings.CONFIG.OUTPUT_DIR, quiet=quiet).BINARIES.chrome
# return self.__class__.model_validate(
#     {
#         **self.model_dump(),
#         "loaded_abspath": chrome_bin.symlink,
#         "loaded_version": chrome_bin.version,
#         "loaded_binprovider": env,
#         "binproviders_supported": self.binproviders_supported,
#     }
# )


CHROME_BINARY = ChromeBinary()

PLUGIN_BINARIES = [CHROME_BINARY]

class PuppeteerPlugin(BasePlugin):
    app_label: str ='puppeteer'
    verbose_name: str = 'SingleFile'

    hooks: List[InstanceOf[BaseHook]] = [
        PUPPETEER_CONFIG,
        PUPPETEER_BINPROVIDER,
        CHROME_BINARY,
    ]



PLUGIN = PuppeteerPlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
