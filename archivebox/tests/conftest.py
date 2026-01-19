"""archivebox/tests/conftest.py - Pytest fixtures for CLI tests."""

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pytest


# =============================================================================
# CLI Helpers (defined before fixtures that use them)
# =============================================================================

def run_archivebox_cmd(
    args: List[str],
    data_dir: Path,
    stdin: Optional[str] = None,
    timeout: int = 60,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[str, str, int]:
    """
    Run archivebox command via subprocess, return (stdout, stderr, returncode).

    Args:
        args: Command arguments (e.g., ['crawl', 'create', 'https://example.com'])
        data_dir: The DATA_DIR to use
        stdin: Optional string to pipe to stdin
        timeout: Command timeout in seconds
        env: Additional environment variables

    Returns:
        Tuple of (stdout, stderr, returncode)
    """
    cmd = [sys.executable, '-m', 'archivebox'] + args

    base_env = os.environ.copy()
    base_env['DATA_DIR'] = str(data_dir)
    base_env['USE_COLOR'] = 'False'
    base_env['SHOW_PROGRESS'] = 'False'
    # Disable slow extractors for faster tests
    base_env['SAVE_ARCHIVEDOTORG'] = 'False'
    base_env['SAVE_TITLE'] = 'False'
    base_env['SAVE_FAVICON'] = 'False'
    base_env['SAVE_WGET'] = 'False'
    base_env['SAVE_WARC'] = 'False'
    base_env['SAVE_PDF'] = 'False'
    base_env['SAVE_SCREENSHOT'] = 'False'
    base_env['SAVE_DOM'] = 'False'
    base_env['SAVE_SINGLEFILE'] = 'False'
    base_env['SAVE_READABILITY'] = 'False'
    base_env['SAVE_MERCURY'] = 'False'
    base_env['SAVE_GIT'] = 'False'
    base_env['SAVE_YTDLP'] = 'False'
    base_env['SAVE_HEADERS'] = 'False'
    base_env['SAVE_HTMLTOTEXT'] = 'False'

    if env:
        base_env.update(env)

    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=data_dir,
        env=base_env,
        timeout=timeout,
    )

    return result.stdout, result.stderr, result.returncode


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def isolated_data_dir(tmp_path):
    """
    Create isolated DATA_DIR for each test.

    Uses tmp_path for complete isolation.
    """
    data_dir = tmp_path / 'archivebox_data'
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def initialized_archive(isolated_data_dir):
    """
    Initialize ArchiveBox archive in isolated directory.

    Runs `archivebox init` via subprocess to set up database and directories.
    """
    stdout, stderr, returncode = run_archivebox_cmd(
        ['init', '--quick'],
        data_dir=isolated_data_dir,
        timeout=60,
    )
    assert returncode == 0, f"archivebox init failed: {stderr}"
    return isolated_data_dir


# =============================================================================
# Output Assertions
# =============================================================================

def parse_jsonl_output(stdout: str) -> List[Dict[str, Any]]:
    """Parse JSONL output into list of dicts via Process parser."""
    from archivebox.machine.models import Process
    return Process.parse_records_from_text(stdout or '')


def assert_jsonl_contains_type(stdout: str, record_type: str, min_count: int = 1):
    """Assert output contains at least min_count records of type."""
    records = parse_jsonl_output(stdout)
    matching = [r for r in records if r.get('type') == record_type]
    assert len(matching) >= min_count, \
        f"Expected >= {min_count} {record_type}, got {len(matching)}"
    return matching


def assert_jsonl_pass_through(stdout: str, input_records: List[Dict[str, Any]]):
    """Assert that input records appear in output (pass-through behavior)."""
    output_records = parse_jsonl_output(stdout)
    output_ids = {r.get('id') for r in output_records if r.get('id')}

    for input_rec in input_records:
        input_id = input_rec.get('id')
        if input_id:
            assert input_id in output_ids, \
                f"Input record {input_id} not found in output (pass-through failed)"


def assert_record_has_fields(record: Dict[str, Any], required_fields: List[str]):
    """Assert record has all required fields with non-None values."""
    for field in required_fields:
        assert field in record, f"Record missing field: {field}"
        assert record[field] is not None, f"Record field is None: {field}"


# =============================================================================
# Test Data Factories
# =============================================================================

def create_test_url(domain: str = 'example.com', path: str = None) -> str:
    """Generate unique test URL."""
    import uuid
    path = path or uuid.uuid4().hex[:8]
    return f'https://{domain}/{path}'


def create_test_crawl_json(urls: List[str] = None, **kwargs) -> Dict[str, Any]:
    """Create Crawl JSONL record for testing."""
    urls = urls or [create_test_url()]
    return {
        'type': 'Crawl',
        'urls': '\n'.join(urls),
        'max_depth': kwargs.get('max_depth', 0),
        'tags_str': kwargs.get('tags_str', ''),
        'status': kwargs.get('status', 'queued'),
        **{k: v for k, v in kwargs.items() if k not in ('max_depth', 'tags_str', 'status')},
    }


def create_test_snapshot_json(url: str = None, **kwargs) -> Dict[str, Any]:
    """Create Snapshot JSONL record for testing."""
    return {
        'type': 'Snapshot',
        'url': url or create_test_url(),
        'tags_str': kwargs.get('tags_str', ''),
        'status': kwargs.get('status', 'queued'),
        **{k: v for k, v in kwargs.items() if k not in ('tags_str', 'status')},
    }
