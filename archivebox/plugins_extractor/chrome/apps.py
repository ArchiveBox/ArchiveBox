import platform
from pathlib import Path
from typing import List, Optional, Dict, ClassVar

from django.conf import settings

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field
from pydantic_pkgr import (
    BinProvider,
    BinName,
    BinProviderName,
    ProviderLookupDict,
    bin_abspath,
)

# Depends on other Django apps:
from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet, ConfigSectionName
from plugantic.base_binary import BaseBinary, env
# from plugantic.base_extractor import BaseExtractor
# from plugantic.base_queue import BaseQueue
from plugantic.base_hook import BaseHook

# Depends on Other Plugins:
from plugins_pkg.puppeteer.apps import PUPPETEER_BINPROVIDER
from plugins_pkg.playwright.apps import PLAYWRIGHT_BINPROVIDER


CHROMIUM_BINARY_NAMES_LINUX = [
    "chromium",
    "chromium-browser",
    "chromium-browser-beta",
    "chromium-browser-unstable",
    "chromium-browser-canary",
    "chromium-browser-dev",
]
CHROMIUM_BINARY_NAMES_MACOS = ["/Applications/Chromium.app/Contents/MacOS/Chromium"]
CHROMIUM_BINARY_NAMES = CHROMIUM_BINARY_NAMES_LINUX + CHROMIUM_BINARY_NAMES_MACOS

CHROME_BINARY_NAMES_LINUX = [
    "google-chrome",
    "google-chrome-stable",
    "google-chrome-beta",
    "google-chrome-canary",
    "google-chrome-unstable",
    "google-chrome-dev",
    "chrome"
]
CHROME_BINARY_NAMES_MACOS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
]
CHROME_BINARY_NAMES = CHROME_BINARY_NAMES_LINUX + CHROME_BINARY_NAMES_MACOS


def autodetect_system_chrome_install(PATH=None) -> Optional[Path]:
    for bin_name in CHROME_BINARY_NAMES + CHROMIUM_BINARY_NAMES:
        abspath = bin_abspath(bin_name, PATH=env.PATH)
        if abspath:
            return abspath
    return None

def create_macos_app_symlink(target: Path, shortcut: Path):
    """
    on macOS, some binaries are inside of .app, so we need to
    create a tiny bash script instead of a symlink
    (so that ../ parent relationships are relative to original .app instead of callsite dir)
    """
    # TODO: should we enforce this? is it useful in any other situation?
    # if platform.system().lower() != 'darwin':
    #     raise Exception(...)
        
    shortcut.write_text(f"""#!/usr/bin/env bash\nexec '{target}' "$@"\n""")
    shortcut.chmod(0o777)   # make sure its executable by everyone

###################### Config ##########################


class ChromeDependencyConfigs(BaseConfigSet):
    section: ClassVar[ConfigSectionName] = "DEPENDENCY_CONFIG"

    CHROME_BINARY: str = Field(default='chrome')
    CHROME_ARGS: Optional[List[str]] = Field(default=None)
    CHROME_EXTRA_ARGS: List[str] = []
    CHROME_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']
    
    # def load(self) -> Self:
    #     # for each field in the model, load its value
    #     # load from each source in order of precedence (lowest to highest):
    #     # - schema default
    #     # - ArchiveBox.conf INI file
    #     # - environment variables
    #     # - command-line arguments
        
    #     LOADED_VALUES: Dict[str, Any] = {}

    #     for field_name, field in self.__fields__.items():
    #         def_value   = field.default_factory() if field.default_factory else field.default
    #         ini_value   = settings.INI_CONFIG.get_value(field_name)
    #         env_value   = settings.ENV_CONFIG.get_value(field_name)
    #         cli_value   = settings.CLI_CONFIG.get_value(field_name)
    #         run_value   = settings.RUN_CONFIG.get_value(field_name)
    #         value = run_value or cli_value or env_value or ini_value or def_value

class ChromeConfigs(ChromeDependencyConfigs):
    # section: ConfigSectionName = 'ALL_CONFIGS'
    pass

DEFAULT_GLOBAL_CONFIG = {
}

CHROME_CONFIG = ChromeConfigs(**DEFAULT_GLOBAL_CONFIG)


class ChromeBinary(BaseBinary):
    name: BinName = CHROME_CONFIG.CHROME_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [PUPPETEER_BINPROVIDER, env, PLAYWRIGHT_BINPROVIDER]
    
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        env.name: {
            'abspath': lambda: autodetect_system_chrome_install(PATH=env.PATH),  # /usr/bin/google-chrome-stable
        },
        PUPPETEER_BINPROVIDER.name: {
            'packages': lambda: ['chrome@stable'],              # npx @puppeteer/browsers install chrome@stable
        },
        PLAYWRIGHT_BINPROVIDER.name: {
            'packages': lambda: ['chromium'],                   # playwright install chromium
        },
    }

    @staticmethod
    def symlink_to_lib(binary, bin_dir=settings.CONFIG.BIN_DIR) -> None:
        if not (binary.abspath and binary.abspath.exists()):
            return
        bin_dir.mkdir(parents=True, exist_ok=True)
        symlink = bin_dir / binary.name
        
        if platform.system().lower() == 'darwin':
            # if on macOS, browser binary is inside a .app, so we need to create a tiny bash script instead of a symlink
            create_macos_app_symlink(binary.abspath, symlink)
        else:
            # otherwise on linux we can symlink directly to binary executable
            symlink.symlink_to(binary.abspath)


CHROME_BINARY = ChromeBinary()

PLUGIN_BINARIES = [CHROME_BINARY]

class ChromePlugin(BasePlugin):
    app_label: str = 'chrome'
    verbose_name: str = 'Chrome Browser'

    hooks: List[InstanceOf[BaseHook]] = [
        CHROME_CONFIG,
        CHROME_BINARY,
    ]



PLUGIN = ChromePlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
