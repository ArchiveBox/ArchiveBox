import platform
from pathlib import Path
from typing import List, Optional, Dict

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
from builtin_plugins.puppeteer.apps import PUPPETEER_BINPROVIDER
from builtin_plugins.playwright.apps import PLAYWRIGHT_BINPROVIDER


CHROMIUM_BINARY_NAMES = [
    "chromium",
    "chromium-browser",
    "chromium-browser-beta",
    "chromium-browser-unstable",
    "chromium-browser-canary",
    "chromium-browser-dev",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
CHROME_BINARY_NAMES = [
    "google-chrome",
    "google-chrome-stable",
    "google-chrome-beta",
    "google-chrome-canary",
    "google-chrome-unstable",
    "google-chrome-dev",
    # 'chrome',
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
]


def autodetect_system_chrome_install(PATH=None) -> Optional[Path]:
    for bin_name in CHROME_BINARY_NAMES + CHROMIUM_BINARY_NAMES:
        abspath = bin_abspath(bin_name, PATH=env.PATH)
        if abspath:
            return abspath
    return None

###################### Config ##########################


class ChromeDependencyConfigs(BaseConfigSet):
    section: ConfigSectionName = 'DEPENDENCY_CONFIG'

    CHROME_BINARY: str = Field(default='wget')
    CHROME_ARGS: Optional[List[str]] = Field(default=None)
    CHROME_EXTRA_ARGS: List[str] = []
    CHROME_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']

class ChromeConfigs(ChromeDependencyConfigs):
    # section: ConfigSectionName = 'ALL_CONFIGS'
    pass

DEFAULT_GLOBAL_CONFIG = {
}

CHROME_CONFIG = ChromeConfigs(**DEFAULT_GLOBAL_CONFIG)


class ChromeBinary(BaseBinary):
    name: BinName = 'chrome'
    binproviders_supported: List[InstanceOf[BinProvider]] = [PUPPETEER_BINPROVIDER, env, PLAYWRIGHT_BINPROVIDER]
    
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        env.name: {
            'abspath': lambda:
                autodetect_system_chrome_install(PATH=env.PATH),
        },
        PUPPETEER_BINPROVIDER.name: {
            'packages': lambda:
                ['chrome@stable'],
        },
        PLAYWRIGHT_BINPROVIDER.name: {
            'packages': lambda:
                ['chromium'],
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
            symlink.write_text(f"""#!/usr/bin/env bash\nexec '{binary.abspath}' "$@"\n""")
            symlink.chmod(0o777)   # make sure its executable by everyone
        else:
            # otherwise on linux we can symlink directly to binary executable
            symlink.symlink_to(binary.abspath)


CHROME_BINARY = ChromeBinary()

PLUGIN_BINARIES = [CHROME_BINARY]

class ChromePlugin(BasePlugin):
    app_label: str ='puppeteer'
    verbose_name: str = 'Chrome & Playwright'

    hooks: List[InstanceOf[BaseHook]] = [
        CHROME_CONFIG,
        CHROME_BINARY,
    ]



PLUGIN = ChromePlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
