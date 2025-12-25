#!/usr/bin/env python3
"""
Install readability-extractor if not already available.

Runs at crawl start to ensure readability-extractor is installed.
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

        # Note: npm package is from github:ArchiveBox/readability-extractor
        readability_binary = Binary(
            name='readability-extractor',
            binproviders=[NpmProvider(), EnvProvider()],
            overrides={'npm': {'packages': ['github:ArchiveBox/readability-extractor']}}
        )

        # Try to load, install if not found
        try:
            loaded = readability_binary.load()
            if not loaded or not loaded.abspath:
                raise Exception("Not loaded")
        except Exception:
            # Install via npm from GitHub repo
            loaded = readability_binary.install()

        if loaded and loaded.abspath:
            # Output InstalledBinary JSONL
            print(json.dumps({
                'type': 'InstalledBinary',
                'name': 'readability-extractor',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256,
                'binprovider': loaded.loaded_binprovider.name if loaded.loaded_binprovider else 'unknown',
            }))
            sys.exit(0)
        else:
            print(json.dumps({
                'type': 'Dependency',
                'bin_name': 'readability-extractor',
                'bin_providers': 'npm,env',
            }))
            print("Failed to install readability-extractor", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'readability-extractor',
            'bin_providers': 'npm,env',
        }))
        print(f"Error installing readability-extractor: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
