#!/usr/bin/env python3
"""
Install Chromium via the Puppeteer CLI.

Usage: on_Binary__12_puppeteer_install.py --binary-id=<uuid> --machine-id=<uuid> --name=<name>
Output: Binary JSONL record to stdout after installation
"""

import json
import os
import re
import sys
from pathlib import Path

import rich_click as click
from abx_pkg import Binary, EnvProvider, NpmProvider, BinProviderOverrides

# Fix pydantic forward reference issue
NpmProvider.model_rebuild()


@click.command()
@click.option('--machine-id', required=True, help='Machine UUID')
@click.option('--binary-id', required=True, help='Binary UUID')
@click.option('--name', required=True, help='Binary name to install')
@click.option('--binproviders', default='*', help='Allowed providers (comma-separated)')
@click.option('--overrides', default=None, help='JSON-encoded overrides dict')
def main(machine_id: str, binary_id: str, name: str, binproviders: str, overrides: str | None) -> None:
    if binproviders != '*' and 'puppeteer' not in binproviders.split(','):
        sys.exit(0)

    if name not in ('chromium', 'chrome'):
        sys.exit(0)

    lib_dir = os.environ.get('LIB_DIR', '').strip()
    if not lib_dir:
        click.echo('ERROR: LIB_DIR environment variable not set', err=True)
        sys.exit(1)

    npm_prefix = Path(lib_dir) / 'npm'
    npm_prefix.mkdir(parents=True, exist_ok=True)
    npm_provider = NpmProvider(npm_prefix=npm_prefix)
    cache_dir = Path(lib_dir) / 'puppeteer'
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('PUPPETEER_CACHE_DIR', str(cache_dir))

    puppeteer_binary = Binary(
        name='puppeteer',
        binproviders=[npm_provider, EnvProvider()],
        overrides={'npm': {'packages': ['puppeteer']}},
    ).load()

    if not puppeteer_binary.abspath:
        click.echo('ERROR: puppeteer binary not found (install puppeteer first)', err=True)
        sys.exit(1)

    install_args = _parse_override_packages(overrides, default=['chromium@latest', '--install-deps'])
    cmd = ['browsers', 'install', *install_args]
    proc = puppeteer_binary.exec(cmd=cmd, timeout=300)
    if proc.returncode != 0:
        click.echo(proc.stdout.strip(), err=True)
        click.echo(proc.stderr.strip(), err=True)
        click.echo(f'ERROR: puppeteer install failed ({proc.returncode})', err=True)
        sys.exit(1)

    chromium_binary = _load_chromium_binary(proc.stdout + '\n' + proc.stderr)
    if not chromium_binary or not chromium_binary.abspath:
        click.echo('ERROR: failed to locate Chromium after install', err=True)
        sys.exit(1)

    _emit_chromium_binary_record(
        binary=chromium_binary,
        machine_id=machine_id,
        binary_id=binary_id,
    )

    config_patch = {
        'CHROME_BINARY': str(chromium_binary.abspath),
        'CHROMIUM_VERSION': str(chromium_binary.version) if chromium_binary.version else '',
    }

    print(json.dumps({
        'type': 'Machine',
        'config': config_patch,
    }))

    sys.exit(0)


def _parse_override_packages(overrides: str | None, default: list[str]) -> list[str]:
    if not overrides:
        return default
    try:
        overrides_dict = json.loads(overrides)
    except json.JSONDecodeError:
        return default

    if isinstance(overrides_dict, dict):
        provider_overrides = overrides_dict.get('puppeteer')
        if isinstance(provider_overrides, dict):
            packages = provider_overrides.get('packages')
            if isinstance(packages, list) and packages:
                return [str(arg) for arg in packages]
        if isinstance(provider_overrides, list) and provider_overrides:
            return [str(arg) for arg in provider_overrides]
    if isinstance(overrides_dict, list) and overrides_dict:
        return [str(arg) for arg in overrides_dict]

    return default


def _emit_chromium_binary_record(binary: Binary, machine_id: str, binary_id: str) -> None:
    record = {
        'type': 'Binary',
        'name': 'chromium',
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'puppeteer',
        'machine_id': machine_id,
        'binary_id': binary_id,
    }
    print(json.dumps(record))


def _load_chromium_binary(output: str) -> Binary | None:
    candidates: list[Path] = []
    match = re.search(r'(?:chromium|chrome)@[^\s]+\s+(\S+)', output)
    if match:
        candidates.append(Path(match.group(1)))

    cache_dirs: list[Path] = []
    cache_env = os.environ.get('PUPPETEER_CACHE_DIR')
    if cache_env:
        cache_dirs.append(Path(cache_env))

    home = Path.home()
    cache_dirs.extend([
        home / '.cache' / 'puppeteer',
        home / 'Library' / 'Caches' / 'puppeteer',
    ])

    for base in cache_dirs:
        for root in (base, base / 'chromium', base / 'chrome'):
            try:
                candidates.extend(root.rglob('Chromium.app/Contents/MacOS/Chromium'))
            except Exception:
                pass
            try:
                candidates.extend(root.rglob('chrome'))
            except Exception:
                pass

    for candidate in candidates:
        try:
            binary = Binary(
                name='chromium',
                binproviders=[EnvProvider()],
                overrides={'env': {'abspath': str(candidate)}},
            ).load()
        except Exception:
            continue
        if binary.abspath:
            return binary

    return None


if __name__ == '__main__':
    main()
