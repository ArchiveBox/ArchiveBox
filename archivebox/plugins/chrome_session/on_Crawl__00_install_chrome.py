#!/usr/bin/env python3
"""
Install Chrome/Chromium if not already available.

Runs at crawl start to ensure Chrome is installed.
Uses playwright to install chromium if no system Chrome found.
Outputs JSONL for InstalledBinary.
"""

import json
import sys
import os
import shutil
from pathlib import Path


def find_chrome():
    """Try to find system Chrome/Chromium."""
    # Comprehensive list of Chrome/Chromium binary names and paths
    chromium_names_linux = [
        'chromium',
        'chromium-browser',
        'chromium-browser-beta',
        'chromium-browser-unstable',
        'chromium-browser-canary',
        'chromium-browser-dev',
    ]

    chrome_names_linux = [
        'google-chrome',
        'google-chrome-stable',
        'google-chrome-beta',
        'google-chrome-canary',
        'google-chrome-unstable',
        'google-chrome-dev',
        'chrome',
    ]

    chrome_paths_macos = [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
    ]

    chrome_paths_linux = [
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        '/snap/bin/chromium',
        '/opt/google/chrome/chrome',
    ]

    all_chrome_names = chrome_names_linux + chromium_names_linux
    all_chrome_paths = chrome_paths_macos + chrome_paths_linux

    # Check env var first
    env_path = os.environ.get('CHROME_BINARY', '')
    if env_path and Path(env_path).is_file():
        return env_path

    # Try shutil.which for various names
    for name in all_chrome_names:
        abspath = shutil.which(name)
        if abspath:
            return abspath

    # Check common paths
    for path in all_chrome_paths:
        if Path(path).is_file():
            return path

    return None


def main():
    try:
        # First try to find system Chrome
        system_chrome = find_chrome()
        if system_chrome:
            print(json.dumps({
                'type': 'InstalledBinary',
                'name': 'chrome',
                'abspath': str(system_chrome),
                'version': None,
                'sha256': None,
                'binprovider': 'env',
            }))
            sys.exit(0)

        # If not found in system, try to install chromium via apt/brew
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider, BinProviderOverrides

        AptProvider.model_rebuild()
        BrewProvider.model_rebuild()
        EnvProvider.model_rebuild()

        # Try chromium-browser or chromium via system package managers
        for binary_name in ['chromium', 'chromium-browser', 'google-chrome']:
            try:
                chrome_binary = Binary(
                    name=binary_name,
                    binproviders=[AptProvider(), BrewProvider(), EnvProvider()]
                )

                # Try to load, install if not found
                try:
                    loaded = chrome_binary.load()
                    if not loaded or not loaded.abspath:
                        raise Exception("Not loaded")
                except Exception:
                    # Install via system package manager
                    loaded = chrome_binary.install()

                if loaded and loaded.abspath:
                    # Output InstalledBinary JSONL
                    print(json.dumps({
                        'type': 'InstalledBinary',
                        'name': 'chrome',
                        'abspath': str(loaded.abspath),
                        'version': str(loaded.version) if loaded.version else None,
                        'sha256': loaded.sha256,
                        'binprovider': loaded.loaded_binprovider.name if loaded.loaded_binprovider else 'unknown',
                    }))
                    sys.exit(0)
            except Exception:
                continue

        # If all attempts failed
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'chrome',
            'bin_providers': 'apt,brew,env',
        }))
        print("Failed to install Chrome/Chromium", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'chrome',
            'bin_providers': 'apt,brew,env',
        }))
        print(f"Error installing Chrome: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
