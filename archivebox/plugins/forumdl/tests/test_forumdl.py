"""
Integration tests for forumdl plugin

Tests verify:
    pass
1. Hook script exists
2. Dependencies installed via validation hooks
3. Verify deps with abx-pkg
4. Forum extraction works on forum URLs
5. JSONL output is correct
6. Config options work
7. Handles non-forum URLs gracefully
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
FORUMDL_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_forumdl.*'), None)
TEST_URL = 'https://example.com'

# Module-level cache for binary path
_forumdl_binary_path = None
_forumdl_lib_root = None

def get_forumdl_binary_path():
    """Get the installed forum-dl binary path from cache or by running installation."""
    global _forumdl_binary_path
    if _forumdl_binary_path:
        return _forumdl_binary_path

    # Try to find forum-dl binary using abx-pkg
    from abx_pkg import Binary, PipProvider, EnvProvider, BinProviderOverrides

    try:
        binary = Binary(
            name='forum-dl',
            binproviders=[PipProvider(), EnvProvider()]
        ).load()

        if binary and binary.abspath:
            _forumdl_binary_path = str(binary.abspath)
            return _forumdl_binary_path
    except Exception:
        pass

    # If not found, try to install via pip using the crawl hook overrides
    pip_hook = PLUGINS_ROOT / 'pip' / 'on_Binary__11_pip_install.py'
    crawl_hook = PLUGIN_DIR / 'on_Crawl__25_forumdl_install.py'
    if pip_hook.exists():
        binary_id = str(uuid.uuid4())
        machine_id = str(uuid.uuid4())
        overrides = None

        if crawl_hook.exists():
            crawl_result = subprocess.run(
                [sys.executable, str(crawl_hook)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for crawl_line in crawl_result.stdout.strip().split('\n'):
                if crawl_line.strip().startswith('{'):
                    try:
                        crawl_record = json.loads(crawl_line)
                        if crawl_record.get('type') == 'Binary' and crawl_record.get('name') == 'forum-dl':
                            overrides = crawl_record.get('overrides')
                            break
                    except json.JSONDecodeError:
                        continue

        # Create a persistent temp LIB_DIR for the pip provider
        import platform
        global _forumdl_lib_root
        if not _forumdl_lib_root:
            _forumdl_lib_root = tempfile.mkdtemp(prefix='forumdl-lib-')
        machine = platform.machine().lower()
        system = platform.system().lower()
        if machine in ('arm64', 'aarch64'):
            machine = 'arm64'
        elif machine in ('x86_64', 'amd64'):
            machine = 'x86_64'
        machine_type = f"{machine}-{system}"
        lib_dir = Path(_forumdl_lib_root) / 'lib' / machine_type
        lib_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env['LIB_DIR'] = str(lib_dir)
        env['DATA_DIR'] = str(Path(_forumdl_lib_root) / 'data')

        cmd = [
            sys.executable, str(pip_hook),
            '--binary-id', binary_id,
            '--machine-id', machine_id,
            '--name', 'forum-dl'
        ]
        if overrides:
            cmd.append(f'--overrides={json.dumps(overrides)}')

        install_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )

        # Parse Binary from pip installation
        for install_line in install_result.stdout.strip().split('\n'):
            if install_line.strip():
                try:
                    install_record = json.loads(install_line)
                    if install_record.get('type') == 'Binary' and install_record.get('name') == 'forum-dl':
                        _forumdl_binary_path = install_record.get('abspath')
                        return _forumdl_binary_path
                except json.JSONDecodeError:
                    pass

    return None


def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert FORUMDL_HOOK.exists(), f"Hook not found: {FORUMDL_HOOK}"


def test_verify_deps_with_abx_pkg():
    """Verify forum-dl is installed by calling the REAL installation hooks."""
    binary_path = get_forumdl_binary_path()
    if not binary_path:
        assert False, (
            "forum-dl installation failed. Install hook should install forum-dl automatically. "
            "Note: forum-dl has a dependency on cchardet which may not compile on Python 3.14+ "
            "due to removed longintrepr.h header."
        )
    assert Path(binary_path).is_file(), f"Binary path must be a valid file: {binary_path}"


def test_handles_non_forum_url():
    """Test that forum-dl extractor handles non-forum URLs gracefully via hook."""
    import os

    binary_path = get_forumdl_binary_path()
    if not binary_path:
        pass
    assert Path(binary_path).is_file(), f"Binary must be a valid file: {binary_path}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        env = os.environ.copy()
        env['FORUMDL_BINARY'] = binary_path

        # Run forum-dl extraction hook on non-forum URL
        result = subprocess.run(
            [sys.executable, str(FORUMDL_HOOK), '--url', 'https://example.com', '--snapshot-id', 'test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Should exit 0 even for non-forum URL (graceful handling)
        assert result.returncode == 0, f"Should handle non-forum URL gracefully: {result.stderr}"

        # Parse clean JSONL output
        result_json = None
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line.startswith('{'):
                pass
                try:
                    record = json.loads(line)
                    if record.get('type') == 'ArchiveResult':
                        result_json = record
                        break
                except json.JSONDecodeError:
                    pass

        assert result_json, "Should have ArchiveResult JSONL output"
        assert result_json['status'] == 'succeeded', f"Should succeed even for non-forum URL: {result_json}"


def test_config_save_forumdl_false_skips():
    """Test that FORUMDL_ENABLED=False exits without emitting JSONL."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['FORUMDL_ENABLED'] = 'False'

        result = subprocess.run(
            [sys.executable, str(FORUMDL_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when feature disabled: {result.stderr}"

        # Feature disabled - temporary failure, should NOT emit JSONL
        assert 'Skipping' in result.stderr or 'False' in result.stderr, "Should log skip reason to stderr"

        # Should NOT emit any JSONL
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL when feature disabled, but got: {jsonl_lines}"


def test_config_timeout():
    """Test that FORUMDL_TIMEOUT config is respected."""
    import os

    binary_path = get_forumdl_binary_path()
    if not binary_path:
        pass
    assert Path(binary_path).is_file(), f"Binary must be a valid file: {binary_path}"

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['FORUMDL_BINARY'] = binary_path
        env['FORUMDL_TIMEOUT'] = '5'

        start_time = time.time()
        result = subprocess.run(
            [sys.executable, str(FORUMDL_HOOK), '--url', 'https://example.com', '--snapshot-id', 'testtimeout'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=10  # Should complete in 5s, use 10s as safety margin
        )
        elapsed_time = time.time() - start_time

        assert result.returncode == 0, f"Should complete without hanging: {result.stderr}"
        # Allow 1 second overhead for subprocess startup and Python interpreter
        assert elapsed_time <= 6.0, f"Should complete within 6 seconds (5s timeout + 1s overhead), took {elapsed_time:.2f}s"


def test_real_forum_url():
    """Test that forum-dl extracts content from a real HackerNews thread with jsonl output.

    Uses our Pydantic v2 compatible wrapper to fix forum-dl 0.3.0's incompatibility.
    """
    import os

    binary_path = get_forumdl_binary_path()
    assert binary_path, "forum-dl binary not available"
    assert Path(binary_path).is_file(), f"Binary must be a valid file: {binary_path}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Use HackerNews - one of the most reliable forum-dl extractors
        forum_url = 'https://news.ycombinator.com/item?id=1'

        env = os.environ.copy()
        env['FORUMDL_BINARY'] = binary_path
        env['FORUMDL_TIMEOUT'] = '60'
        env['FORUMDL_OUTPUT_FORMAT'] = 'jsonl'  # Use jsonl format
        # HTML output could be added via: env['FORUMDL_ARGS_EXTRA'] = json.dumps(['--files-output', './files'])

        start_time = time.time()
        result = subprocess.run(
            [sys.executable, str(FORUMDL_HOOK), '--url', forum_url, '--snapshot-id', 'testforum'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=90
        )
        elapsed_time = time.time() - start_time

        # Should succeed with our Pydantic v2 wrapper
        assert result.returncode == 0, f"Should extract forum successfully: {result.stderr}"

        # Parse JSONL output
        result_json = None
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line.startswith('{'):
                try:
                    record = json.loads(line)
                    if record.get('type') == 'ArchiveResult':
                        result_json = record
                        break
                except json.JSONDecodeError:
                    pass

        assert result_json, f"Should have ArchiveResult JSONL output. stdout: {result.stdout}"
        assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"

        # Check that forum files were downloaded
        output_files = list(tmpdir.glob('**/*'))
        forum_files = [f for f in output_files if f.is_file()]

        assert len(forum_files) > 0, f"Should have downloaded at least one forum file. Files: {output_files}"

        # Verify the JSONL file has content
        jsonl_file = tmpdir / 'forum.jsonl'
        assert jsonl_file.exists(), "Should have created forum.jsonl"
        assert jsonl_file.stat().st_size > 0, "forum.jsonl should not be empty"

        print(f"Successfully extracted {len(forum_files)} file(s) in {elapsed_time:.2f}s")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
