__package__ = 'archivebox.plugins_extractor.chrome'

import os
import sys
import platform
from pathlib import Path
from typing import List, Optional, Dict

# Depends on other PyPI/vendor packages:
from rich import print
from pydantic import InstanceOf, Field, model_validator
from pydantic_pkgr import (
    BinProvider,
    BinName,
    BinProviderName,
    ProviderLookupDict,
    bin_abspath,
)

# Depends on other Django apps:
from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, env
# from abx.archivebox.base_extractor import BaseExtractor
# from abx.archivebox.base_queue import BaseQueue
from abx.archivebox.base_hook import BaseHook

# Depends on Other Plugins:
from archivebox.config import CONSTANTS
from archivebox.config.common import ARCHIVING_CONFIG, SHELL_CONFIG
from plugins_pkg.puppeteer.apps import PUPPETEER_BINPROVIDER
from plugins_pkg.playwright.apps import PLAYWRIGHT_BINPROVIDER

from archivebox.misc.util import dedupe


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
    shortcut.unlink(missing_ok=True)
    shortcut.write_text(f"""#!/usr/bin/env bash\nexec '{target}' "$@"\n""")
    shortcut.chmod(0o777)   # make sure its executable by everyone

###################### Config ##########################


class ChromeConfig(BaseConfigSet):
    USE_CHROME: bool                        = Field(default=True)

    # Chrome Binary
    CHROME_BINARY: str                      = Field(default='chrome')
    CHROME_DEFAULT_ARGS: List[str]          = Field(default=[
        '--virtual-time-budget=15000',
        '--disable-features=DarkMode',
        "--run-all-compositor-stages-before-draw",
        "--hide-scrollbars",
        "--autoplay-policy=no-user-gesture-required",
        "--no-first-run",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        "--simulate-outdated-no-au='Tue, 31 Dec 2099 23:59:59 GMT'",
    ])
    CHROME_EXTRA_ARGS: List[str]           = Field(default=[])
    
    # Chrome Options Tuning
    CHROME_TIMEOUT: int                     = Field(default=lambda: ARCHIVING_CONFIG.TIMEOUT - 10)
    CHROME_HEADLESS: bool                   = Field(default=True)
    CHROME_SANDBOX: bool                    = Field(default=lambda: not SHELL_CONFIG.IN_DOCKER)
    CHROME_RESOLUTION: str                  = Field(default=lambda: ARCHIVING_CONFIG.RESOLUTION)
    CHROME_CHECK_SSL_VALIDITY: bool         = Field(default=lambda: ARCHIVING_CONFIG.CHECK_SSL_VALIDITY)
    
    # Cookies & Auth
    CHROME_USER_AGENT: str                  = Field(default=lambda: ARCHIVING_CONFIG.USER_AGENT)
    CHROME_USER_DATA_DIR: Path | None       = Field(default=None)
    CHROME_PROFILE_NAME: str                = Field(default='Default')

    # Extractor Toggles
    SAVE_SCREENSHOT: bool                   = Field(default=True, alias='FETCH_SCREENSHOT')
    SAVE_DOM: bool                          = Field(default=True, alias='FETCH_DOM')
    SAVE_PDF: bool                          = Field(default=True, alias='FETCH_PDF')

    @model_validator(mode='after')
    def validate_use_chrome(self):
        if self.USE_CHROME and self.CHROME_TIMEOUT < 15:
            print(f'[red][!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={self.CHROME_TIMEOUT} seconds)[/red]', file=sys.stderr)
            print('    Chrome will fail to archive all sites if set to less than ~15 seconds.', file=sys.stderr)
            print('    (Setting it to somewhere between 30 and 300 seconds is recommended)', file=sys.stderr)
            print(file=sys.stderr)
            print('    If you want to make ArchiveBox run faster, disable specific archive methods instead:', file=sys.stderr)
            print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#archive-method-toggles', file=sys.stderr)
            print(file=sys.stderr)
            
        # if user has specified a user data dir, make sure its valid
        if self.CHROME_USER_DATA_DIR and os.access(self.CHROME_USER_DATA_DIR, os.R_OK):
            # check to make sure user_data_dir/<profile_name> exists
            if not (self.CHROME_USER_DATA_DIR / self.CHROME_PROFILE_NAME).is_dir():
                print(f'[red][X] Could not find profile "{self.CHROME_PROFILE_NAME}" in CHROME_USER_DATA_DIR.[/red]', file=sys.stderr)
                print(f'    {self.CHROME_USER_DATA_DIR}', file=sys.stderr)
                print('    Make sure you set it to a Chrome user data directory containing a Default profile folder.', file=sys.stderr)
                print('    For more info see:', file=sys.stderr)
                print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#CHROME_USER_DATA_DIR', file=sys.stderr)
                if '/Default' in str(self.CHROME_USER_DATA_DIR):
                    print(file=sys.stderr)
                    print('    Try removing /Default from the end e.g.:', file=sys.stderr)
                    print('        CHROME_USER_DATA_DIR="{}"'.format(str(self.CHROME_USER_DATA_DIR).split('/Default')[0]), file=sys.stderr)
                
                # hard error is too annoying here, instead just set it to nothing
                # raise SystemExit(2)
                self.CHROME_USER_DATA_DIR = None
        else:
            self.CHROME_USER_DATA_DIR = None
            
        return self

    def chrome_args(self, **options) -> List[str]:
        """helper to build up a chrome shell command with arguments"""
    
        # Chrome CLI flag documentation: https://peter.sh/experiments/chromium-command-line-switches/
    
        options = self.model_copy(update=options)
    
        cmd_args = [*options.CHROME_DEFAULT_ARGS, *options.CHROME_EXTRA_ARGS]
    
        if options.CHROME_HEADLESS:
            cmd_args += ["--headless=new"]   # expects chrome version >= 111
    
        if not options.CHROME_SANDBOX:
            # assume this means we are running inside a docker container
            # in docker, GPU support is limited, sandboxing is unecessary,
            # and SHM is limited to 64MB by default (which is too low to be usable).
            cmd_args += (
                "--no-sandbox",
                "--no-zygote",
                "--disable-dev-shm-usage",
                "--disable-software-rasterizer",
                "--disable-sync",
                # "--password-store=basic",
            )

    
        # set window size for screenshot/pdf/etc. rendering
        cmd_args += ('--window-size={}'.format(options.CHROME_RESOLUTION),)
    
        if not options.CHROME_CHECK_SSL_VALIDITY:
            cmd_args += ('--disable-web-security', '--ignore-certificate-errors')
    
        if options.CHROME_USER_AGENT:
            cmd_args += ('--user-agent={}'.format(options.CHROME_USER_AGENT),)
    
        # this no longer works on newer chrome version for some reason, just causes chrome to hang indefinitely:
        # if options.CHROME_TIMEOUT:
        #   cmd_args += ('--timeout={}'.format(options.CHROME_TIMEOUT * 1000),)
    
        if options.CHROME_USER_DATA_DIR:
            cmd_args.append('--user-data-dir={}'.format(options.CHROME_USER_DATA_DIR))
            cmd_args.append('--profile-directory={}'.format(options.CHROME_PROFILE_NAME or 'Default'))
    
        return dedupe(cmd_args)

CHROME_CONFIG = ChromeConfig()


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
    def symlink_to_lib(binary, bin_dir=CONSTANTS.LIB_BIN_DIR) -> None:
        if not (binary.abspath and os.access(binary.abspath, os.F_OK)):
            return
        
        bin_dir.mkdir(parents=True, exist_ok=True)
        symlink = bin_dir / binary.name
        
        try:
            if platform.system().lower() == 'darwin':
                # if on macOS, browser binary is inside a .app, so we need to create a tiny bash script instead of a symlink
                create_macos_app_symlink(binary.abspath, symlink)
            else:
                # otherwise on linux we can symlink directly to binary executable
                symlink.unlink(missing_ok=True)
                symlink.symlink_to(binary.abspath)
        except Exception as err:
            # print(f'[red]:warning: Failed to symlink {symlink} -> {binary.abspath}[/red] {err}')
            # not actually needed, we can just run without it
            pass

    @staticmethod            
    def chrome_cleanup_lockfile():
        """
        Cleans up any state or runtime files that chrome leaves behind when killed by
        a timeout or other error
        """
        lock_file = Path("~/.config/chromium/SingletonLock").expanduser()

        if SHELL_CONFIG.IN_DOCKER and os.access(lock_file, os.F_OK):
            lock_file.unlink()
        
        if CHROME_CONFIG.CHROME_USER_DATA_DIR:
            if os.access(CHROME_CONFIG.CHROME_USER_DATA_DIR / 'SingletonLock', os.F_OK):
                lock_file.unlink()



CHROME_BINARY = ChromeBinary()


class ChromePlugin(BasePlugin):
    app_label: str = 'chrome'
    verbose_name: str = 'Chrome Browser'

    hooks: List[InstanceOf[BaseHook]] = [
        CHROME_CONFIG,
        CHROME_BINARY,
    ]



PLUGIN = ChromePlugin()
# PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
