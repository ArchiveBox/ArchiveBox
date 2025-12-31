"""archivebox/tests/conftest.py - Pytest fixtures for CLI tests."""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pytest


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def isolated_data_dir(tmp_path, settings):
    """
    Create isolated DATA_DIR for each test.

    Uses tmp_path for isolation, configures Django settings.
    """
    data_dir = tmp_path / 'archivebox_data'
    data_dir.mkdir()

    # Set environment for subprocess calls
    os.environ['DATA_DIR'] = str(data_dir)

    # Update Django settings
    settings.DATA_DIR = data_dir

    yield data_dir

    # Cleanup handled by tmp_path fixture


@pytest.fixture
def initialized_archive(isolated_data_dir):
    """
    Initialize ArchiveBox archive in isolated directory.

    Runs `archivebox init` to set up database and directories.
    """
    from archivebox.cli.archivebox_init import init
    init(setup=True, quick=True)
    return isolated_data_dir


@pytest.fixture
def cli_env(initialized_archive):
    """
    Environment dict for CLI subprocess calls.

    Includes DATA_DIR and disables slow extractors.
    """
    return {
        **os.environ,
        'DATA_DIR': str(initialized_archive),
        'USE_COLOR': 'False',
        'SHOW_PROGRESS': 'False',
        'SAVE_TITLE': 'True',
        'SAVE_FAVICON': 'False',
        'SAVE_WGET': 'False',
        'SAVE_WARC': 'False',
        'SAVE_PDF': 'False',
        'SAVE_SCREENSHOT': 'False',
        'SAVE_DOM': 'False',
        'SAVE_SINGLEFILE': 'False',
        'SAVE_READABILITY': 'False',
        'SAVE_MERCURY': 'False',
        'SAVE_GIT': 'False',
        'SAVE_YTDLP': 'False',
        'SAVE_HEADERS': 'False',
    }


# =============================================================================
# CLI Helpers
# =============================================================================

def run_archivebox_cmd(
    args: List[str],
    stdin: Optional[str] = None,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 60,
) -> Tuple[str, str, int]:
    """
    Run archivebox command, return (stdout, stderr, returncode).

    Args:
        args: Command arguments (e.g., ['crawl', 'create', 'https://example.com'])
        stdin: Optional string to pipe to stdin
        cwd: Working directory (defaults to DATA_DIR from env)
        env: Environment variables (defaults to os.environ with DATA_DIR)
        timeout: Command timeout in seconds

    Returns:
        Tuple of (stdout, stderr, returncode)
    """
    cmd = [sys.executable, '-m', 'archivebox'] + args

    env = env or {**os.environ}
    cwd = cwd or Path(env.get('DATA_DIR', '.'))

    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=timeout,
    )

    return result.stdout, result.stderr, result.returncode


# =============================================================================
# Output Assertions
# =============================================================================

def parse_jsonl_output(stdout: str) -> List[Dict[str, Any]]:
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
# Database Assertions
# =============================================================================

def assert_db_count(model_class, filters: Dict[str, Any], expected: int):
    """Assert database count matches expected."""
    actual = model_class.objects.filter(**filters).count()
    assert actual == expected, \
        f"Expected {expected} {model_class.__name__}, got {actual}"


def assert_db_exists(model_class, **filters):
    """Assert at least one record exists matching filters."""
    assert model_class.objects.filter(**filters).exists(), \
        f"No {model_class.__name__} found matching {filters}"


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
    from archivebox.misc.jsonl import TYPE_CRAWL

    urls = urls or [create_test_url()]
    return {
        'type': TYPE_CRAWL,
        'urls': '\n'.join(urls),
        'max_depth': kwargs.get('max_depth', 0),
        'tags_str': kwargs.get('tags_str', ''),
        'status': kwargs.get('status', 'queued'),
        **{k: v for k, v in kwargs.items() if k not in ('max_depth', 'tags_str', 'status')},
    }


def create_test_snapshot_json(url: str = None, **kwargs) -> Dict[str, Any]:
    """Create Snapshot JSONL record for testing."""
    from archivebox.misc.jsonl import TYPE_SNAPSHOT

    return {
        'type': TYPE_SNAPSHOT,
        'url': url or create_test_url(),
        'tags_str': kwargs.get('tags_str', ''),
        'status': kwargs.get('status', 'queued'),
        **{k: v for k, v in kwargs.items() if k not in ('tags_str', 'status')},
    }
