#!/usr/bin/env python3
"""
Install hook for yt-dlp and its dependencies (node, ffmpeg).

Runs at crawl start to verify yt-dlp and required binaries are available.
Outputs JSONL for InstalledBinary and Machine config updates.
Respects YTDLP_BINARY, NODE_BINARY, FFMPEG_BINARY env vars.
"""

import os
import sys
import json
from pathlib import Path


def get_bin_name(env_var: str, default: str) -> str:
    """Get binary name from env var or use default."""
    configured = os.environ.get(env_var, '').strip()
    if configured:
        if '/' in configured:
            return Path(configured).name
        return configured
    return default


def find_ytdlp() -> dict | None:
    """Find yt-dlp binary, respecting YTDLP_BINARY env var."""
    try:
        from abx_pkg import Binary, PipProvider, BrewProvider, AptProvider, EnvProvider

        bin_name = get_bin_name('YTDLP_BINARY', 'yt-dlp')
        binary = Binary(name=bin_name, binproviders=[PipProvider(), BrewProvider(), AptProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': bin_name,
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def find_node() -> dict | None:
    """Find node binary, respecting NODE_BINARY env var."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

        bin_name = get_bin_name('NODE_BINARY', 'node')
        binary = Binary(name=bin_name, binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': bin_name,
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def find_ffmpeg() -> dict | None:
    """Find ffmpeg binary, respecting FFMPEG_BINARY env var."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

        bin_name = get_bin_name('FFMPEG_BINARY', 'ffmpeg')
        binary = Binary(name=bin_name, binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': bin_name,
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def main():
    # Check for yt-dlp (required)
    ytdlp_result = find_ytdlp()

    # Check for node (required for JS extraction)
    node_result = find_node()

    # Check for ffmpeg (required for video conversion)
    ffmpeg_result = find_ffmpeg()

    missing_deps = []

    # Get configured binary names
    ytdlp_bin_name = get_bin_name('YTDLP_BINARY', 'yt-dlp')
    node_bin_name = get_bin_name('NODE_BINARY', 'node')
    ffmpeg_bin_name = get_bin_name('FFMPEG_BINARY', 'ffmpeg')

    # Emit results for yt-dlp
    if ytdlp_result and ytdlp_result.get('abspath'):
        print(json.dumps({
            'type': 'InstalledBinary',
            'name': ytdlp_result['name'],
            'abspath': ytdlp_result['abspath'],
            'version': ytdlp_result['version'],
            'sha256': ytdlp_result['sha256'],
            'binprovider': ytdlp_result['binprovider'],
        }))

        print(json.dumps({
            'type': 'Machine',
            '_method': 'update',
            'key': 'config/YTDLP_BINARY',
            'value': ytdlp_result['abspath'],
        }))

        if ytdlp_result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/YTDLP_VERSION',
                'value': ytdlp_result['version'],
            }))
    else:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': ytdlp_bin_name,
            'bin_providers': 'pip,brew,apt,env',
        }))
        missing_deps.append(ytdlp_bin_name)

    # Emit results for node
    if node_result and node_result.get('abspath'):
        print(json.dumps({
            'type': 'InstalledBinary',
            'name': node_result['name'],
            'abspath': node_result['abspath'],
            'version': node_result['version'],
            'sha256': node_result['sha256'],
            'binprovider': node_result['binprovider'],
        }))

        print(json.dumps({
            'type': 'Machine',
            '_method': 'update',
            'key': 'config/NODE_BINARY',
            'value': node_result['abspath'],
        }))

        if node_result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/NODE_VERSION',
                'value': node_result['version'],
            }))
    else:
        # node is installed as 'nodejs' package on apt
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': node_bin_name,
            'bin_providers': 'apt,brew,env',
            'overrides': {
                'apt': {'packages': ['nodejs']}
            }
        }))
        missing_deps.append(node_bin_name)

    # Emit results for ffmpeg
    if ffmpeg_result and ffmpeg_result.get('abspath'):
        print(json.dumps({
            'type': 'InstalledBinary',
            'name': ffmpeg_result['name'],
            'abspath': ffmpeg_result['abspath'],
            'version': ffmpeg_result['version'],
            'sha256': ffmpeg_result['sha256'],
            'binprovider': ffmpeg_result['binprovider'],
        }))

        print(json.dumps({
            'type': 'Machine',
            '_method': 'update',
            'key': 'config/FFMPEG_BINARY',
            'value': ffmpeg_result['abspath'],
        }))

        if ffmpeg_result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/FFMPEG_VERSION',
                'value': ffmpeg_result['version'],
            }))
    else:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': ffmpeg_bin_name,
            'bin_providers': 'apt,brew,env',
        }))
        missing_deps.append(ffmpeg_bin_name)

    if missing_deps:
        print(f"Missing dependencies: {', '.join(missing_deps)}", file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
