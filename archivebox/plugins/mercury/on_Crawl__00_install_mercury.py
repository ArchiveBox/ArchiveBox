#!/usr/bin/env python3
"""
Install mercury-parser if not already available.

Runs at crawl start to ensure mercury-parser is installed.
Outputs JSONL for InstalledBinary.
"""

import json
import sys
from pathlib import Path


def main():
    try:
        from abx_pkg import Binary, NpmProvider, EnvProvider, BinProviderOverrides

        NpmProvider.model_rebuild()
        EnvProvider.model_rebuild()

        # Note: npm package is @postlight/mercury-parser, binary is mercury-parser
        mercury_binary = Binary(
            name='mercury-parser',
            binproviders=[NpmProvider(), EnvProvider()],
            overrides={'npm': {'packages': ['@postlight/mercury-parser']}}
        )

        # Try to load, install if not found
        try:
            loaded = mercury_binary.load()
            if not loaded or not loaded.abspath:
                raise Exception("Not loaded")
        except Exception:
            # Install via npm
            loaded = mercury_binary.install()

        if loaded and loaded.abspath:
            # Output InstalledBinary JSONL
            print(json.dumps({
                'type': 'InstalledBinary',
                'name': 'mercury-parser',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256,
                'binprovider': loaded.loaded_binprovider.name if loaded.loaded_binprovider else 'unknown',
            }))
            sys.exit(0)
        else:
            print(json.dumps({
                'type': 'Dependency',
                'bin_name': 'mercury-parser',
                'bin_providers': 'npm,env',
            }))
            print("Failed to install mercury-parser", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'mercury-parser',
            'bin_providers': 'npm,env',
        }))
        print(f"Error installing mercury-parser: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
