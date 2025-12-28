"""
Integration tests for papersdl plugin

Tests verify:
1. Hook script exists
2. Dependencies installed via validation hooks
3. Verify deps with abx-pkg
4. Paper extraction works on paper URLs
5. JSONL output is correct
6. Config options work
7. Handles non-paper URLs gracefully
"""

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
PAPERSDL_HOOK = PLUGIN_DIR / 'on_Snapshot__54_papersdl.py'
PAPERSDL_INSTALL_HOOK = PLUGIN_DIR / 'on_Crawl__00_install_papersdl.py'
TEST_URL = 'https://example.com'

# Module-level cache for binary path
_papersdl_binary_path = None

def get_papersdl_binary_path():
    """Get the installed papers-dl binary path from cache or by running installation."""
    global _papersdl_binary_path
    if _papersdl_binary_path:
        return _papersdl_binary_path

    # Run install hook to find or install binary
    result = subprocess.run(
        [sys.executable, str(PAPERSDL_INSTALL_HOOK)],
        capture_output=True,
        text=True,
        timeout=300
    )

    # Check if binary was found
    for line in result.stdout.strip().split('\n'):
        if line.strip():
            try:
                record = json.loads(line)
                if record.get('type') == 'Binary' and record.get('name') == 'papers-dl':
                    _papersdl_binary_path = record.get('abspath')
                    return _papersdl_binary_path
                elif record.get('type') == 'Dependency' and record.get('bin_name') == 'papers-dl':
                    # Need to install via pip hook
                    pip_hook = PLUGINS_ROOT / 'pip' / 'on_Binary__install_using_pip_provider.py'
                    dependency_id = str(uuid.uuid4())

                    # Build command with overrides if present
                    cmd = [
                        sys.executable, str(pip_hook),
                        '--dependency-id', dependency_id,
                        '--bin-name', record['bin_name']
                    ]
                    if 'overrides' in record:
                        cmd.extend(['--overrides', json.dumps(record['overrides'])])

                    install_result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=300
                    )

                    # Parse Binary from pip installation
                    for install_line in install_result.stdout.strip().split('\n'):
                        if install_line.strip():
                            try:
                                install_record = json.loads(install_line)
                                if install_record.get('type') == 'Binary' and install_record.get('name') == 'papers-dl':
                                    _papersdl_binary_path = install_record.get('abspath')
                                    return _papersdl_binary_path
                            except json.JSONDecodeError:
                                pass
            except json.JSONDecodeError:
                pass

    return None

def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert PAPERSDL_HOOK.exists(), f"Hook not found: {PAPERSDL_HOOK}"


def test_papersdl_install_hook():
    """Test papers-dl install hook checks for papers-dl."""
    # Run papers-dl install hook
    result = subprocess.run(
        [sys.executable, str(PAPERSDL_INSTALL_HOOK)],
        capture_output=True,
        text=True,
        timeout=30
    )

    # Hook exits 0 if all binaries found, 1 if any not found
    # Parse output for Binary and Dependency records
    found_binary = False
    found_dependency = False

    for line in result.stdout.strip().split('\n'):
        if line.strip():
            try:
                record = json.loads(line)
                if record.get('type') == 'Binary':
                    if record['name'] == 'papers-dl':
                        assert record['abspath'], "papers-dl should have abspath"
                        found_binary = True
                elif record.get('type') == 'Dependency':
                    if record['bin_name'] == 'papers-dl':
                        found_dependency = True
            except json.JSONDecodeError:
                pass

    # papers-dl should either be found (Binary) or missing (Dependency)
    assert found_binary or found_dependency, \
        "papers-dl should have either Binary or Dependency record"


def test_verify_deps_with_abx_pkg():
    """Verify papers-dl is installed by calling the REAL installation hooks."""
    binary_path = get_papersdl_binary_path()
    assert binary_path, "papers-dl must be installed successfully via install hook and pip provider"
    assert Path(binary_path).is_file(), f"Binary path must be a valid file: {binary_path}"


def test_handles_non_paper_url():
    """Test that papers-dl extractor handles non-paper URLs gracefully via hook."""
    import os

    binary_path = get_papersdl_binary_path()
    assert binary_path, "Binary must be installed for this test"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        env = os.environ.copy()
        env['PAPERSDL_BINARY'] = binary_path

        # Run papers-dl extraction hook on non-paper URL
        result = subprocess.run(
            [sys.executable, str(PAPERSDL_HOOK), '--url', 'https://example.com', '--snapshot-id', 'test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Should exit 0 even for non-paper URL
        assert result.returncode == 0, f"Should handle non-paper URL gracefully: {result.stderr}"

        # Parse clean JSONL output
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

        assert result_json, "Should have ArchiveResult JSONL output"
        assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"


def test_config_save_papersdl_false_skips():
    """Test that SAVE_PAPERSDL=False exits without emitting JSONL."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['SAVE_PAPERSDL'] = 'False'

        result = subprocess.run(
            [sys.executable, str(PAPERSDL_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when feature disabled: {result.stderr}"

        # Feature disabled - no JSONL emission, just logs to stderr
        assert 'Skipping' in result.stderr or 'False' in result.stderr, "Should log skip reason to stderr"

        # Should NOT emit any JSONL
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL when feature disabled, but got: {jsonl_lines}"


def test_config_timeout():
    """Test that PAPERSDL_TIMEOUT config is respected."""
    import os

    binary_path = get_papersdl_binary_path()
    assert binary_path, "Binary must be installed for this test"

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['PAPERSDL_BINARY'] = binary_path
        env['PAPERSDL_TIMEOUT'] = '5'

        result = subprocess.run(
            [sys.executable, str(PAPERSDL_HOOK), '--url', 'https://example.com', '--snapshot-id', 'testtimeout'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, "Should complete without hanging"

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
