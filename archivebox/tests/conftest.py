"""archivebox/tests/conftest.py - Pytest fixtures for CLI tests."""

import os
import sys
import subprocess
import textwrap
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pytest

from archivebox.uuid_compat import uuid7

pytest_plugins = ["archivebox.tests.fixtures"]


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
# CWD-based CLI Helpers (no DATA_DIR env)
# =============================================================================

def run_archivebox_cmd_cwd(
    args: List[str],
    cwd: Path,
    stdin: Optional[str] = None,
    timeout: int = 60,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[str, str, int]:
    """
    Run archivebox command via subprocess using cwd as DATA_DIR (no DATA_DIR env).
    Returns (stdout, stderr, returncode).
    """
    cmd = [sys.executable, '-m', 'archivebox'] + args

    base_env = os.environ.copy()
    base_env.pop('DATA_DIR', None)
    base_env['USE_COLOR'] = 'False'
    base_env['SHOW_PROGRESS'] = 'False'

    if env:
        base_env.update(env)

    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=base_env,
        timeout=timeout,
    )

    return result.stdout, result.stderr, result.returncode


def stop_process(proc: subprocess.Popen[str]) -> Tuple[str, str]:
    if proc.poll() is None:
        proc.terminate()
        try:
            return proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return proc.communicate()


def run_python_cwd(
    script: str,
    cwd: Path,
    timeout: int = 60,
) -> Tuple[str, str, int]:
    base_env = os.environ.copy()
    base_env.pop('DATA_DIR', None)
    result = subprocess.run(
        [sys.executable, '-'],
        input=script,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=base_env,
        timeout=timeout,
    )
    return result.stdout, result.stderr, result.returncode


def wait_for_archive_outputs(
    cwd: Path,
    url: str,
    timeout: int = 120,
    interval: float = 1.0,
) -> bool:
    script = textwrap.dedent(
        f"""\
        from pathlib import Path

        import os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(url={url!r}).order_by('-created_at').first()
        if snapshot is None or snapshot.status != 'sealed':
            raise SystemExit(1)

        output_rel = None
        for output in snapshot.discover_outputs():
            candidate = output.get('path')
            if not candidate or candidate.startswith('responses/'):
                continue
            if Path(snapshot.output_dir, candidate).is_file():
                output_rel = candidate
                break
        if output_rel is None:
            fallback = Path(snapshot.output_dir, 'index.jsonl')
            if fallback.exists():
                output_rel = 'index.jsonl'
        if output_rel is None:
            snapshot_dir = Path(snapshot.output_dir)
            for candidate in snapshot_dir.rglob('*'):
                if not candidate.is_file():
                    continue
                rel_path = candidate.relative_to(snapshot_dir)
                if rel_path.parts and rel_path.parts[0] == 'responses':
                    continue
                if rel_path.name in {'stdout.log', 'stderr.log', 'cmd.sh'}:
                    continue
                output_rel = str(rel_path)
                break
        if output_rel is None:
            raise SystemExit(1)

        responses_root = Path(snapshot.output_dir) / 'responses' / snapshot.domain
        if not responses_root.exists():
            raise SystemExit(1)
        if not any(candidate.is_file() for candidate in responses_root.rglob('*')):
            raise SystemExit(1)

        print('READY')
        """
    )

    deadline = time.time() + timeout
    while time.time() < deadline:
        stdout, _stderr, returncode = run_python_cwd(script, cwd=cwd, timeout=30)
        if returncode == 0 and 'READY' in stdout:
            return True
        time.sleep(interval)
    return False

def _get_machine_type() -> str:
    import platform

    os_name = platform.system().lower()
    arch = platform.machine().lower()
    in_docker = os.environ.get('IN_DOCKER', '').lower() in ('1', 'true', 'yes')
    suffix = '-docker' if in_docker else ''
    return f'{arch}-{os_name}{suffix}'

def _find_cached_chromium(lib_dir: Path) -> Optional[Path]:
    candidates = [
        lib_dir / 'puppeteer',
        lib_dir / 'npm' / 'node_modules' / 'puppeteer' / '.local-chromium',
    ]
    for base in candidates:
        if not base.exists():
            continue
        for path in base.rglob('Chromium.app/Contents/MacOS/Chromium'):
            return path
        for path in base.rglob('chrome-linux/chrome'):
            return path
        for path in base.rglob('chrome-linux64/chrome'):
            return path
    return None

def _find_system_browser() -> Optional[Path]:
    candidates = [
        Path('/Applications/Chromium.app/Contents/MacOS/Chromium'),
        Path('/usr/bin/chromium'),
        Path('/usr/bin/chromium-browser'),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None

def _ensure_puppeteer(shared_lib: Path) -> None:
    npm_prefix = shared_lib / 'npm'
    node_modules = npm_prefix / 'node_modules'
    puppeteer_dir = node_modules / 'puppeteer'
    if puppeteer_dir.exists():
        return
    npm_prefix.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['PUPPETEER_SKIP_DOWNLOAD'] = '1'
    subprocess.run(
        ['npm', 'install', 'puppeteer'],
        cwd=str(npm_prefix),
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )


@pytest.fixture(scope="class")
def real_archive_with_example(tmp_path_factory, request):
    """
    Initialize archive and add https://example.com using responses only.
    Uses cwd for DATA_DIR.
    """
    tmp_path = tmp_path_factory.mktemp("archivebox_data")
    if getattr(request, "cls", None) is not None:
        request.cls.data_dir = tmp_path

    stdout, stderr, returncode = run_archivebox_cmd_cwd(
        ['init', '--quick'],
        cwd=tmp_path,
        timeout=120,
    )
    assert returncode == 0, f"archivebox init failed: {stderr}"

    stdout, stderr, returncode = run_archivebox_cmd_cwd(
        [
            'config',
            '--set',
            'LISTEN_HOST=archivebox.localhost:8000',
            'PUBLIC_INDEX=True',
            'PUBLIC_SNAPSHOTS=True',
            'PUBLIC_ADD_VIEW=True',
        ],
        cwd=tmp_path,
    )
    assert returncode == 0, f"archivebox config failed: {stderr}"

    add_env = {
        'RESPONSES_ENABLED': 'True',
        'SHOW_PROGRESS': 'False',
        'USE_COLOR': 'False',
        'RESPONSES_TIMEOUT': '30',
    }
    cmd = [sys.executable, '-m', 'archivebox', 'add', '--depth=0', '--plugins=responses', 'https://example.com']
    base_env = os.environ.copy()
    base_env.pop('DATA_DIR', None)
    base_env['USE_COLOR'] = 'False'
    base_env['SHOW_PROGRESS'] = 'False'
    base_env.update(add_env)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=tmp_path,
        env=base_env,
    )

    ready = wait_for_archive_outputs(tmp_path, 'https://example.com', timeout=600)
    stdout, stderr = stop_process(proc)
    assert ready, f"archivebox add did not produce required outputs within timeout:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

    return tmp_path


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
    path = path or uuid7().hex[:8]
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
