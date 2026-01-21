"""archivebox/tests/conftest.py - Pytest fixtures for CLI tests."""

import os
import shutil
import sys
import subprocess
import textwrap
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
    Initialize archive and add https://example.com using chrome+responses only.
    Uses cwd for DATA_DIR and symlinks lib dir to a shared cache.
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

    machine_type = _get_machine_type()
    shared_root = Path(__file__).resolve().parents[3] / 'tmp' / 'test_lib_cache'
    shared_lib = shared_root / machine_type
    shared_lib.mkdir(parents=True, exist_ok=True)

    lib_target = tmp_path / 'lib' / machine_type
    if lib_target.exists() and not lib_target.is_symlink():
        shutil.rmtree(lib_target)
    if not lib_target.exists():
        lib_target.parent.mkdir(parents=True, exist_ok=True)
        lib_target.symlink_to(shared_lib, target_is_directory=True)

    _ensure_puppeteer(shared_lib)
    cached_chromium = _find_cached_chromium(shared_lib)
    if cached_chromium:
        browser_binary = cached_chromium
    else:
        browser_binary = _find_system_browser()
        if browser_binary:
            chromium_link = shared_lib / 'chromium-bin'
            if not chromium_link.exists():
                chromium_link.symlink_to(browser_binary)
            browser_binary = chromium_link

    if browser_binary:
        stdout, stderr, returncode = run_archivebox_cmd_cwd(
            [f'config', '--set', f'CHROME_BINARY={browser_binary}'],
            cwd=tmp_path,
        )
        assert returncode == 0, f"archivebox config CHROME_BINARY failed: {stderr}"
        script = textwrap.dedent(f"""\
        import os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()
        from django.utils import timezone
        from archivebox.machine.models import Binary, Machine
        machine = Machine.current()
        Binary.objects.filter(machine=machine, name='chromium').update(
            status='installed',
            abspath='{browser_binary}',
            binprovider='env',
            retry_at=timezone.now(),
        )
        Binary.objects.update_or_create(
            machine=machine,
            name='chromium',
            defaults={{
                'status': 'installed',
                'abspath': '{browser_binary}',
                'binprovider': 'env',
                'retry_at': timezone.now(),
            }},
        )
        print('OK')
        """
        )
        stdout, stderr, returncode = run_python_cwd(script, cwd=tmp_path, timeout=60)
        assert returncode == 0, f"Register chromium binary failed: {stderr}"

    add_env = {
        'CHROME_ENABLED': 'True',
        'RESPONSES_ENABLED': 'True',
        'DOM_ENABLED': 'False',
        'SHOW_PROGRESS': 'False',
        'USE_COLOR': 'False',
        'CHROME_HEADLESS': 'True',
        'CHROME_PAGELOAD_TIMEOUT': '45',
        'CHROME_TIMEOUT': '60',
        'RESPONSES_TIMEOUT': '30',
    }
    if browser_binary:
        add_env['CHROME_BINARY'] = str(browser_binary)
    if cached_chromium:
        add_env['PUPPETEER_CACHE_DIR'] = str(shared_lib / 'puppeteer')
    stdout, stderr, returncode = run_archivebox_cmd_cwd(
        ['add', '--depth=0', '--plugins=chrome,responses', 'https://example.com'],
        cwd=tmp_path,
        timeout=600,
        env=add_env,
    )
    assert returncode == 0, f"archivebox add failed: {stderr}"

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
