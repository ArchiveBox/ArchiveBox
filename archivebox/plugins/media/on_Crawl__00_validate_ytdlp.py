#!/usr/bin/env python3
"""
Validation hook for yt-dlp and its dependencies (node, ffmpeg).

Runs at crawl start to verify yt-dlp and required binaries are available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import sys
import json


def find_ytdlp() -> dict | None:
    """Find yt-dlp binary."""
    try:
        from abx_pkg import Binary, PipProvider, BrewProvider, AptProvider, EnvProvider

        binary = Binary(name='yt-dlp', binproviders=[PipProvider(), BrewProvider(), AptProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'yt-dlp',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def find_node() -> dict | None:
    """Find node binary."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

        binary = Binary(name='node', binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'node',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def find_ffmpeg() -> dict | None:
    """Find ffmpeg binary."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

        binary = Binary(name='ffmpeg', binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'ffmpeg',
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
            'bin_name': 'yt-dlp',
            'bin_providers': 'pip,brew,apt,env',
        }))
        missing_deps.append('yt-dlp')

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
            'bin_name': 'node',
            'bin_providers': 'apt,brew,env',
            'overrides': {
                'apt': {'packages': ['nodejs']}
            }
        }))
        missing_deps.append('node')

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
            'bin_name': 'ffmpeg',
            'bin_providers': 'apt,brew,env',
        }))
        missing_deps.append('ffmpeg')

    if missing_deps:
        print(f"Missing dependencies: {', '.join(missing_deps)}", file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
