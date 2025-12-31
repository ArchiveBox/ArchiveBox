"""archivebox/tests/conftest.py - Pytest fixtures for CLI tests."""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pytest


def run_archivebox_cmd(
    args: List[str],
    data_dir: Path,
    stdin: Optional[str] = None,
    timeout: int = 60,
) -> Tuple[str, str, int]:
    """
    Run archivebox command via subprocess, return (stdout, stderr, returncode).
    """
    cmd = [sys.executable, '-m', 'archivebox'] + args

    env = os.environ.copy()
    env['DATA_DIR'] = str(data_dir)
    env['USE_COLOR'] = 'False'
    env['SHOW_PROGRESS'] = 'False'
    # Enable only HEADERS extractor (pure Python, no Chrome) - disable all others
    env['SAVE_HEADERS'] = 'True'
    for extractor in ['TITLE', 'FAVICON', 'WGET', 'WARC', 'PDF', 'SCREENSHOT',
                      'DOM', 'SINGLEFILE', 'READABILITY', 'MERCURY', 'GIT',
                      'YTDLP', 'HTMLTOTEXT', 'ARCHIVEDOTORG']:
        env[f'SAVE_{extractor}'] = 'False'
    # Speed up network operations
    env['TIMEOUT'] = '5'
    env['CHECK_SSL_VALIDITY'] = 'False'

    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=data_dir,
        env=env,
        timeout=timeout,
    )
    return result.stdout, result.stderr, result.returncode


@pytest.fixture(scope="module")
def shared_archive(tmp_path_factory):
    """
    Module-scoped archive - init runs ONCE per test file.
    Much faster than per-test initialization.
    """
    data_dir = tmp_path_factory.mktemp("archivebox_data")
    stdout, stderr, returncode = run_archivebox_cmd(
        ['init', '--quick'],
        data_dir=data_dir,
        timeout=60,
    )
    assert returncode == 0, f"archivebox init failed: {stderr}"
    return data_dir


def parse_jsonl(stdout: str) -> List[Dict[str, Any]]:
    """Parse JSONL output into list of dicts."""
    records = []
    for line in stdout.strip().split('\n'):
        line = line.strip()
        if line and line.startswith('{'):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def create_url(suffix: str = "") -> str:
    """Generate test URL."""
    import uuid
    return f'https://example.com/{suffix or uuid.uuid4().hex[:8]}'
