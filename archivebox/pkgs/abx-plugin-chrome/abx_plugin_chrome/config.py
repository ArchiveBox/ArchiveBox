#!/usr/bin/env python3

import os
from pathlib import Path
import sys
from typing import List, Optional

from pydantic import Field
from abx_pkg import bin_abspath

from abx_spec_config.base_configset import BaseConfigSet
from abx_plugin_default_binproviders import env

from archivebox.config import CONSTANTS
from archivebox.config.common import ARCHIVING_CONFIG, SHELL_CONFIG
from archivebox.misc.util import dedupe
from archivebox.misc.logging import STDERR
from archivebox.misc.logging_util import pretty_path


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

APT_DEPENDENCIES = [
    'apt-transport-https', 'at-spi2-common', 'chromium-browser',
    'fontconfig', 'fonts-freefont-ttf', 'fonts-ipafont-gothic', 'fonts-kacst', 'fonts-khmeros', 'fonts-liberation', 'fonts-noto', 'fonts-noto-color-emoji', 'fonts-symbola', 'fonts-thai-tlwg', 'fonts-tlwg-loma-otf', 'fonts-unifont', 'fonts-wqy-zenhei',
    'libasound2', 'libatk-bridge2.0-0', 'libatk1.0-0', 'libatspi2.0-0', 'libavahi-client3', 'libavahi-common-data', 'libavahi-common3', 'libcairo2', 'libcups2',
    'libdbus-1-3', 'libdrm2', 'libfontenc1', 'libgbm1', 'libglib2.0-0', 'libice6', 'libnspr4', 'libnss3', 'libsm6', 'libunwind8', 'libx11-6', 'libxaw7', 'libxcb1',
    'libxcomposite1', 'libxdamage1', 'libxext6', 'libxfixes3', 'libxfont2', 'libxkbcommon0', 'libxkbfile1', 'libxmu6', 'libxpm4', 'libxrandr2', 'libxt6', 'x11-utils', 'x11-xkb-utils', 'xfonts-encodings',
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


class ChromeConfig(BaseConfigSet):
    USE_CHROME: bool                        = Field(default=True)

    # Chrome Binary
    CHROME_BINARY: str                      = Field(default='chrome')
    CHROME_DEFAULT_ARGS: List[str]          = Field(default=[
        "--disable-sync",
        "--no-pings",
        "--no-first-run",                                              # dont show any first run ui / setup prompts
        "--no-default-browser-check",
        "--disable-default-apps",
        "--ash-no-nudges",
        "--disable-infobars",
        "--disable-blink-features=AutomationControlled",
        "--js-flags=--random-seed=1157259159",
        "--deterministic-mode",
        "--deterministic-fetch",
        "--start-maximized",
        "--test-type=gpu",
        "--disable-search-engine-choice-screen",
        "--disable-session-crashed-bubble", 
        "--hide-crash-restore-bubble",
        "--suppress-message-center-popups",
        "--disable-client-side-phishing-detection",
        "--disable-domain-reliability",
        "--disable-component-update",
        "--disable-datasaver-prompt",
        "--disable-hang-monitor",
        "--disable-session-crashed-bubble",
        "--disable-speech-synthesis-api",
        "--disable-speech-api",
        "--disable-print-preview",
        "--safebrowsing-disable-auto-update",
        "--deny-permission-prompts",
        "--disable-external-intent-requests",
        "--disable-notifications",
        "--disable-desktop-notifications",
        "--noerrdialogs",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--silent-debugger-extension-api",
        "--block-new-web-contents",
        "--metrics-recording-only",
        "--disable-breakpad",
        "--run-all-compositor-stages-before-draw",
        "--use-fake-device-for-media-stream",                          # provide fake camera if site tries to request camera access
        "--simulate-outdated-no-au=Tue, 31 Dec 2099 23:59:59 GMT",   # ignore chrome updates
        "--force-gpu-mem-available-mb=4096",     # allows for longer full page screenshots https://github.com/puppeteer/puppeteer/issues/5530
        "--password-store=basic",
        "--use-mock-keychain",
        "--disable-cookie-encryption",
        "--allow-legacy-extension-manifests",
        "--disable-gesture-requirement-for-media-playback",
        "--font-render-hinting=none",
        "--force-color-profile=srgb",
        "--disable-partial-raster",
        "--disable-skia-runtime-opts",
        "--disable-2d-canvas-clip-aa",
        "--disable-lazy-loading",
        "--disable-renderer-backgrounding",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-ipc-flooding-protection",
        "--disable-extensions-http-throttling",
        "--disable-field-trial-config",
        "--disable-back-forward-cache",
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
    CHROME_USER_DATA_DIR: Path | None       = Field(default=CONSTANTS.PERSONAS_DIR / 'Default' / 'chrome_profile')
    CHROME_PROFILE_NAME: str                = Field(default='Default')

    # Extractor Toggles
    SAVE_SCREENSHOT: bool                   = Field(default=True, alias='FETCH_SCREENSHOT')
    SAVE_DOM: bool                          = Field(default=True, alias='FETCH_DOM')
    SAVE_PDF: bool                          = Field(default=True, alias='FETCH_PDF')
    
    OVERWRITE: bool                         = Field(default=lambda: ARCHIVING_CONFIG.OVERWRITE)

    def validate(self):
        from archivebox.config.paths import create_and_chown_dir

        if self.USE_CHROME and self.CHROME_TIMEOUT < 15:
            STDERR.print()
            STDERR.print(f'[red][!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={self.CHROME_TIMEOUT} seconds)[/red]')
            STDERR.print('    Chrome will fail to archive all sites if set to less than ~15 seconds.')
            STDERR.print('    (Setting it to somewhere between 30 and 300 seconds is recommended)')
            STDERR.print()
            STDERR.print('    If you want to make ArchiveBox run faster, disable specific archive methods instead:')
            STDERR.print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#archive-method-toggles')
            STDERR.print()

        # if user has specified a user data dir, make sure its valid
        if self.USE_CHROME and self.CHROME_USER_DATA_DIR:
            try:
                create_and_chown_dir(self.CHROME_USER_DATA_DIR / self.CHROME_PROFILE_NAME)
            except Exception:
                pass
            
            # check to make sure user_data_dir/<profile_name> exists
            if not os.path.isdir(self.CHROME_USER_DATA_DIR / self.CHROME_PROFILE_NAME):
                STDERR.print()
                STDERR.print()
                STDERR.print(f'[red][X] Could not find profile "{self.CHROME_PROFILE_NAME}" in CHROME_USER_DATA_DIR.[/red]')
                STDERR.print(f'    {self.CHROME_USER_DATA_DIR}')
                STDERR.print('    Make sure you set it to a Chrome user data directory containing a Default profile folder.')
                STDERR.print('    For more info see:')
                STDERR.print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#CHROME_USER_DATA_DIR')
                
                # show special hint if they made the common mistake of putting /Default at the end of the path
                if str(self.CHROME_USER_DATA_DIR).replace(str(CONSTANTS.PERSONAS_DIR / 'Default'), '').endswith('/Default'):
                    STDERR.print()
                    STDERR.print('    Try removing /Default from the end e.g.:')
                    STDERR.print('        CHROME_USER_DATA_DIR="{}"'.format(str(self.CHROME_USER_DATA_DIR).rsplit('/Default', 1)[0]))
                
                self.update_in_place(CHROME_USER_DATA_DIR=None)
            
    @property
    def CHROME_ARGS(self) -> str:
        # import shlex
        # return '\n'.join(shlex.quote(arg) for arg in self.chrome_args())
        return '\n'.join(self.chrome_args())
    def chrome_args(self, **options) -> List[str]:
        """helper to build up a chrome shell command with arguments"""
    
        # Chrome CLI flag documentation: https://peter.sh/experiments/chromium-command-line-switches/
    
        options = self.model_copy(update=options)
    
        cmd_args = [*options.CHROME_DEFAULT_ARGS, *options.CHROME_EXTRA_ARGS]
    
        # if options.CHROME_HEADLESS:
        #     cmd_args += ["--headless"]   # expects chrome version >= 111
    
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
            # remove SingletonLock file
            lockfile = options.CHROME_USER_DATA_DIR / options.CHROME_PROFILE_NAME / 'SingletonLock'
            lockfile.unlink(missing_ok=True)
            
            cmd_args.append('--user-data-dir={}'.format(options.CHROME_USER_DATA_DIR))
            cmd_args.append('--profile-directory={}'.format(options.CHROME_PROFILE_NAME or 'Default'))
        
            # if CHROME_USER_DATA_DIR is set but folder is empty, create a new profile inside it
            if not os.path.isfile(options.CHROME_USER_DATA_DIR / options.CHROME_PROFILE_NAME / 'Preferences'):
                STDERR.print(f'[green]        + creating new Chrome profile in: {pretty_path(options.CHROME_USER_DATA_DIR / options.CHROME_PROFILE_NAME)}[/green]')
                cmd_args.remove('--no-first-run')
                cmd_args.append('--first-run')
    
        return dedupe(cmd_args)

CHROME_CONFIG = ChromeConfig()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        result = getattr(CHROME_CONFIG, sys.argv[1], '')
        if callable(result):
            result = result()
        print(result)
    else:
        print(CHROME_CONFIG.model_dump_json(indent=4))
