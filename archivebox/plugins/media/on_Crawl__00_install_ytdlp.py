#!/usr/bin/env python3
"""
Install yt-dlp if not already available.

Runs at crawl start to ensure yt-dlp is installed.
Outputs JSONL for InstalledBinary.
"""

import json
import sys
from pathlib import Path


def main():
    try:
        from abx_pkg import Binary, PipProvider, EnvProvider, BinProviderOverrides

        PipProvider.model_rebuild()
        EnvProvider.model_rebuild()

        # yt-dlp binary and package have same name
        ytdlp_binary = Binary(
            name='yt-dlp',
            binproviders=[PipProvider(), EnvProvider()]
        )

        # Try to load, install if not found
        try:
            loaded = ytdlp_binary.load()
            if not loaded or not loaded.abspath:
                raise Exception("Not loaded")
        except Exception:
            # Install via pip
            loaded = ytdlp_binary.install()

        if loaded and loaded.abspath:
            # Output InstalledBinary JSONL
            print(json.dumps({
                'type': 'InstalledBinary',
                'name': 'yt-dlp',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256,
                'binprovider': loaded.loaded_binprovider.name if loaded.loaded_binprovider else 'unknown',
            }))
            sys.exit(0)
        else:
            print(json.dumps({
                'type': 'Dependency',
                'bin_name': 'yt-dlp',
                'bin_providers': 'pip,brew,env',
            }))
            print("Failed to install yt-dlp", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'yt-dlp',
            'bin_providers': 'pip,brew,env',
        }))
        print(f"Error installing yt-dlp: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
