#!/usr/bin/env python3
"""
Validation hook for yt-dlp and its dependencies (node, ffmpeg).

Runs at crawl start to verify yt-dlp and required binaries are available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import os
import sys
import json
import shutil
import hashlib
import subprocess
from pathlib import Path


def get_binary_version(abspath: str, version_flag: str = '--version') -> str | None:
    """Get version string from binary."""
    try:
        result = subprocess.run(
            [abspath, version_flag],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            first_line = result.stdout.strip().split('\n')[0]
            return first_line[:64]
    except Exception:
        pass
    return None


def get_binary_hash(abspath: str) -> str | None:
    """Get SHA256 hash of binary."""
    try:
        with open(abspath, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def find_ytdlp() -> dict | None:
    """Find yt-dlp binary."""
    try:
        from abx_pkg import Binary, PipProvider, EnvProvider

        class YtdlpBinary(Binary):
            name: str = 'yt-dlp'
            binproviders_supported = [PipProvider(), EnvProvider()]

        binary = YtdlpBinary()
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'yt-dlp',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback to shutil.which
    abspath = shutil.which('yt-dlp') or os.environ.get('YTDLP_BINARY', '')
    if abspath and Path(abspath).is_file():
        return {
            'name': 'yt-dlp',
            'abspath': abspath,
            'version': get_binary_version(abspath),
            'sha256': get_binary_hash(abspath),
            'binprovider': 'env',
        }

    return None


def find_node() -> dict | None:
    """Find node binary."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

        class NodeBinary(Binary):
            name: str = 'node'
            binproviders_supported = [AptProvider(), BrewProvider(), EnvProvider()]
            overrides: dict = {'apt': {'packages': ['nodejs']}}

        binary = NodeBinary()
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'node',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback to shutil.which
    abspath = shutil.which('node') or os.environ.get('NODE_BINARY', '')
    if abspath and Path(abspath).is_file():
        return {
            'name': 'node',
            'abspath': abspath,
            'version': get_binary_version(abspath),
            'sha256': get_binary_hash(abspath),
            'binprovider': 'env',
        }

    return None


def find_ffmpeg() -> dict | None:
    """Find ffmpeg binary."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

        class FfmpegBinary(Binary):
            name: str = 'ffmpeg'
            binproviders_supported = [AptProvider(), BrewProvider(), EnvProvider()]

        binary = FfmpegBinary()
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'ffmpeg',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback to shutil.which
    abspath = shutil.which('ffmpeg') or os.environ.get('FFMPEG_BINARY', '')
    if abspath and Path(abspath).is_file():
        return {
            'name': 'ffmpeg',
            'abspath': abspath,
            'version': get_binary_version(abspath),
            'sha256': get_binary_hash(abspath),
            'binprovider': 'env',
        }

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
            'bin_providers': 'pip,env',
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
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'node',
            'bin_providers': 'apt,brew,env',
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
