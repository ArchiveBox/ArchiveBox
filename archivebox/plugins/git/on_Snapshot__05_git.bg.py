#!/usr/bin/env python3
"""
Clone a git repository from a URL.

Usage: on_Snapshot__05_git.bg.py --url=<url> --snapshot-id=<uuid>
Output: Clones repository to $PWD/repo

Environment variables:
    GIT_BINARY: Path to git binary
    GIT_TIMEOUT: Timeout in seconds (default: 120)
    GIT_ARGS: Default git arguments (JSON array, default: ["clone", "--depth=1", "--recursive"])
    GIT_ARGS_EXTRA: Extra arguments to append (JSON array, default: [])

    # Fallback to ARCHIVING_CONFIG values if GIT_* not set:
    TIMEOUT: Fallback timeout
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'git'
BIN_NAME = 'git'
BIN_PROVIDERS = 'apt,brew,env'
OUTPUT_DIR = '.'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def get_env_array(name: str, default: list[str] | None = None) -> list[str]:
    """Parse a JSON array from environment variable."""
    val = get_env(name, '')
    if not val:
        return default if default is not None else []
    try:
        result = json.loads(val)
        if isinstance(result, list):
            return [str(item) for item in result]
        return default if default is not None else []
    except json.JSONDecodeError:
        return default if default is not None else []


def is_git_url(url: str) -> bool:
    """Check if URL looks like a git repository."""
    git_patterns = [
        '.git',
        'github.com',
        'gitlab.com',
        'bitbucket.org',
        'git://',
        'ssh://git@',
    ]
    return any(p in url.lower() for p in git_patterns)


def clone_git(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Clone git repository.

    Returns: (success, output_path, error_message)
    """
    timeout = get_env_int('GIT_TIMEOUT') or get_env_int('TIMEOUT', 120)
    git_args = get_env_array('GIT_ARGS', ["clone", "--depth=1", "--recursive"])
    git_args_extra = get_env_array('GIT_ARGS_EXTRA', [])

    cmd = [binary, *git_args, *git_args_extra, url, OUTPUT_DIR]

    try:
        result = subprocess.run(cmd, timeout=timeout)

        if result.returncode == 0 and Path(OUTPUT_DIR).is_dir():
            return True, OUTPUT_DIR, ''
        else:
            return False, None, f'git clone failed (exit={result.returncode})'

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='Git repository URL')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Clone a git repository from a URL."""

    output = None
    status = 'failed'
    error = ''

    try:
        # Check if URL looks like a git repo
        if not is_git_url(url):
            print(f'Skipping git clone for non-git URL: {url}', file=sys.stderr)
            print(json.dumps({
                'type': 'ArchiveResult',
                'status': 'skipped',
                'output_str': 'Not a git URL',
            }))
            sys.exit(0)

        # Get binary from environment
        binary = get_env('GIT_BINARY', 'git')

        # Run extraction
        success, output, error = clone_git(url, binary)
        status = 'succeeded' if success else 'failed'

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    if error:
        print(f'ERROR: {error}', file=sys.stderr)

    # Output clean JSONL (no RESULT_JSON= prefix)
    result = {
        'type': 'ArchiveResult',
        'status': status,
        'output_str': output or error or '',
    }
    print(json.dumps(result))

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
