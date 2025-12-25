#!/usr/bin/env python3
"""
Install git if not already available.

Runs at crawl start to ensure git is installed.
Outputs JSONL for InstalledBinary.
"""

import json
import sys
from pathlib import Path


def main():
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider, BinProviderOverrides

        AptProvider.model_rebuild()
        BrewProvider.model_rebuild()
        EnvProvider.model_rebuild()

        # git binary and package have same name
        git_binary = Binary(
            name='git',
            binproviders=[AptProvider(), BrewProvider(), EnvProvider()]
        )

        # Try to load, install if not found
        try:
            loaded = git_binary.load()
            if not loaded or not loaded.abspath:
                raise Exception("Not loaded")
        except Exception:
            # Install via system package manager
            loaded = git_binary.install()

        if loaded and loaded.abspath:
            # Output InstalledBinary JSONL
            print(json.dumps({
                'type': 'InstalledBinary',
                'name': 'git',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256,
                'binprovider': loaded.loaded_binprovider.name if loaded.loaded_binprovider else 'unknown',
            }))
            sys.exit(0)
        else:
            print(json.dumps({
                'type': 'Dependency',
                'bin_name': 'git',
                'bin_providers': 'apt,brew,env',
            }))
            print("Failed to install git", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'git',
            'bin_providers': 'apt,brew,env',
        }))
        print(f"Error installing git: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
