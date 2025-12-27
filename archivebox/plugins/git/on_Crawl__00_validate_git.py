#!/usr/bin/env python3
"""
Validation hook for git binary.

Runs at crawl start to verify git is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import sys
import json


def find_git() -> dict | None:
    """Find git binary."""
    try:
        from abx_pkg import Binary, EnvProvider

        binary = Binary(name='git', binproviders=[EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'git',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def main():
    result = find_git()

    if result and result.get('abspath'):
        print(json.dumps({
            'type': 'InstalledBinary',
            'name': result['name'],
            'abspath': result['abspath'],
            'version': result['version'],
            'sha256': result['sha256'],
            'binprovider': result['binprovider'],
        }))

        print(json.dumps({
            'type': 'Machine',
            '_method': 'update',
            'key': 'config/GIT_BINARY',
            'value': result['abspath'],
        }))

        if result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/GIT_VERSION',
                'value': result['version'],
            }))

        sys.exit(0)
    else:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'git',
            'bin_providers': 'apt,brew,env',
        }))
        print(f"git binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
