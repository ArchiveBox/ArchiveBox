import os
import platform
from pathlib import Path
from typing import List, Optional

from pydantic import InstanceOf
from abx_pkg import (
    Binary,
    BinProvider,
    BinName,
    BinaryOverrides,
    bin_abspath,
)

import abx

from abx_plugin_default_binproviders import apt, brew, env
from abx_plugin_puppeteer.binproviders import PUPPETEER_BINPROVIDER
from abx_plugin_playwright.binproviders import PLAYWRIGHT_BINPROVIDER


from .config import CHROME_CONFIG

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

CHROME_APT_DEPENDENCIES = [
    'apt-transport-https', 'at-spi2-common',
    'fontconfig', 'fonts-freefont-ttf', 'fonts-ipafont-gothic', 'fonts-kacst', 'fonts-khmeros', 'fonts-liberation', 'fonts-noto', 'fonts-noto-color-emoji', 'fonts-symbola', 'fonts-thai-tlwg', 'fonts-tlwg-loma-otf', 'fonts-unifont', 'fonts-wqy-zenhei',
    'libasound2', 'libatk-bridge2.0-0', 'libatk1.0-0', 'libatspi2.0-0', 'libavahi-client3', 'libavahi-common-data', 'libavahi-common3', 'libcairo2', 'libcups2',
    'libdbus-1-3', 'libdrm2', 'libfontenc1', 'libgbm1', 'libglib2.0-0', 'libice6', 'libnspr4', 'libnss3', 'libsm6', 'libunwind8', 'libx11-6', 'libxaw7', 'libxcb1',
    'libxcomposite1', 'libxdamage1', 'libxext6', 'libxfixes3', 'libxfont2', 'libxkbcommon0', 'libxkbfile1', 'libxmu6', 'libxpm4', 'libxrandr2', 'libxt6', 'x11-utils', 'x11-xkb-utils', 'xfonts-encodings',
    'chromium-browser',
]


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


class ChromeBinary(Binary):
    name: BinName = CHROME_CONFIG.CHROME_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [PUPPETEER_BINPROVIDER, env, PLAYWRIGHT_BINPROVIDER, apt, brew]
    
    overrides: BinaryOverrides = {
        env.name: {
            'abspath': lambda: autodetect_system_chrome_install(PATH=env.PATH),  # /usr/bin/google-chrome-stable
        },
        PUPPETEER_BINPROVIDER.name: {
            'packages': ['chrome@stable'],              # npx @puppeteer/browsers install chrome@stable
        },
        PLAYWRIGHT_BINPROVIDER.name: {
            'packages': ['chromium'],                   # playwright install chromium
        },
        apt.name: {
            'packages': CHROME_APT_DEPENDENCIES,
        },
        brew.name: {
            'packages': ['--cask', 'chromium'] if platform.system().lower() == 'darwin' else [],
        },
    }

    @staticmethod
    def symlink_to_lib(binary, bin_dir=None) -> None:
        bin_dir = bin_dir or abx.pm.hook.get_BIN_DIR()
        
        if not (binary.abspath and os.path.isfile(binary.abspath)):
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
        except Exception:
            # print(f'[red]:warning: Failed to symlink {symlink} -> {binary.abspath}[/red] {err}')
            # not actually needed, we can just run without it
            pass

    @staticmethod            
    def chrome_cleanup_lockfile():
        """
        Cleans up any state or runtime files that chrome leaves behind when killed by
        a timeout or other error
        """
        try:
            linux_lock_file = Path("~/.config/chromium/SingletonLock").expanduser()
            linux_lock_file.unlink(missing_ok=True)
        except Exception:
            pass
        
        if CHROME_CONFIG.CHROME_USER_DATA_DIR:
            try:
                (CHROME_CONFIG.CHROME_USER_DATA_DIR / 'SingletonLock').unlink(missing_ok=True)
            except Exception:
                pass



CHROME_BINARY = ChromeBinary()

