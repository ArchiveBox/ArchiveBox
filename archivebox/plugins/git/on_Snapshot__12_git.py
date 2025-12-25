#!/usr/bin/env python3
"""
Clone a git repository from a URL.

Usage: on_Snapshot__git.py --url=<url> --snapshot-id=<uuid>
Output: Clones repository to $PWD/repo

Environment variables:
    GIT_BINARY: Path to git binary
    TIMEOUT: Timeout in seconds (default: 120)
    GIT_ARGS: Extra arguments for git clone (space-separated)
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'git'
BIN_NAME = 'git'
BIN_PROVIDERS = 'apt,brew,env'
OUTPUT_DIR = 'repo'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


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


def find_git() -> str | None:
    """Find git binary."""
    git = get_env('GIT_BINARY')
    if git and os.path.isfile(git):
        return git

    return shutil.which('git')


def get_version(binary: str) -> str:
    """Get git version."""
    try:
        result = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
        return result.stdout.strip()[:64]
    except Exception:
        return ''


def clone_git(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Clone git repository.

    Returns: (success, output_path, error_message)
    """
    timeout = get_env_int('TIMEOUT', 120)
    extra_args = get_env('GIT_ARGS')

    cmd = [
        binary,
        'clone',
        '--depth=1',
        '--recursive',
    ]

    if extra_args:
        cmd.extend(extra_args.split())

    cmd.extend([url, OUTPUT_DIR])

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)

        if result.returncode == 0 and Path(OUTPUT_DIR).is_dir():
            return True, OUTPUT_DIR, ''
        else:
            stderr = result.stderr.decode('utf-8', errors='replace')
            return False, None, f'git clone failed: {stderr[:200]}'

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='Git repository URL')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Clone a git repository from a URL."""

    start_ts = datetime.now(timezone.utc)
    version = ''
    output = None
    status = 'failed'
    error = ''
    binary = None

    try:
        # Check if URL looks like a git repo
        if not is_git_url(url):
            print(f'Skipping git clone for non-git URL: {url}')
            status = 'skipped'
            end_ts = datetime.now(timezone.utc)
            print(f'START_TS={start_ts.isoformat()}')
            print(f'END_TS={end_ts.isoformat()}')
            print(f'STATUS={status}')
            print(f'RESULT_JSON={json.dumps({"extractor": EXTRACTOR_NAME, "status": status, "url": url})}')
            sys.exit(0)

        # Find binary
        binary = find_git()
        if not binary:
            print(f'ERROR: git binary not found', file=sys.stderr)
            print(f'DEPENDENCY_NEEDED={BIN_NAME}', file=sys.stderr)
            print(f'BIN_PROVIDERS={BIN_PROVIDERS}', file=sys.stderr)
            sys.exit(1)

        version = get_version(binary)

        # Run extraction
        success, output, error = clone_git(url, binary)
        status = 'succeeded' if success else 'failed'

        if success:
            print(f'git clone completed')

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    # Print results
    end_ts = datetime.now(timezone.utc)
    duration = (end_ts - start_ts).total_seconds()

    print(f'START_TS={start_ts.isoformat()}')
    print(f'END_TS={end_ts.isoformat()}')
    print(f'DURATION={duration:.2f}')
    if binary:
        print(f'CMD={binary} clone {url}')
    if version:
        print(f'VERSION={version}')
    if output:
        print(f'OUTPUT={output}')
    print(f'STATUS={status}')

    if error:
        print(f'ERROR={error}', file=sys.stderr)

    # Print JSON result
    result_json = {
        'extractor': EXTRACTOR_NAME,
        'url': url,
        'snapshot_id': snapshot_id,
        'status': status,
        'start_ts': start_ts.isoformat(),
        'end_ts': end_ts.isoformat(),
        'duration': round(duration, 2),
        'cmd_version': version,
        'output': output,
        'error': error or None,
    }
    print(f'RESULT_JSON={json.dumps(result_json)}')

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
