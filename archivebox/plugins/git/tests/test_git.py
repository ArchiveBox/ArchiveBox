"""
Integration tests for git plugin

Tests verify:
1. Validate hook checks for git binary
2. Verify deps with abx-pkg
3. Standalone git extractor execution
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
GIT_HOOK = PLUGIN_DIR / 'on_Snapshot__12_git.py'
GIT_INSTALL_HOOK = PLUGIN_DIR / 'on_Crawl__00_install_git.py'
TEST_URL = 'https://github.com/example/repo.git'

def test_hook_script_exists():
    assert GIT_HOOK.exists()

def test_git_install_hook():
    """Test git install hook checks for git binary."""
    result = subprocess.run(
        [sys.executable, str(GIT_INSTALL_HOOK)],
        capture_output=True,
        text=True,
        timeout=30
    )

    # Hook exits 0 if binary found, 1 if not found (with Dependency record)
    if result.returncode == 0:
        # Binary found - verify Binary JSONL output
        found_binary = False
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    record = json.loads(line)
                    if record.get('type') == 'Binary':
                        assert record['name'] == 'git'
                        assert record['abspath']
                        found_binary = True
                        break
                except json.JSONDecodeError:
                    pass
        assert found_binary, "Should output Binary record when binary found"
    else:
        # Binary not found - verify Dependency JSONL output
        found_dependency = False
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    record = json.loads(line)
                    if record.get('type') == 'Dependency':
                        assert record['bin_name'] == 'git'
                        assert 'env' in record['bin_providers']
                        found_dependency = True
                        break
                except json.JSONDecodeError:
                    pass
        assert found_dependency, "Should output Dependency record when binary not found"

def test_verify_deps_with_abx_pkg():
    """Verify git is available via abx-pkg."""
    from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider, BinProviderOverrides

    git_binary = Binary(name='git', binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
    git_loaded = git_binary.load()

    if git_loaded and git_loaded.abspath:
        assert True, "git is available"
    else:
        pytest.skip("git not available - Dependency record should have been emitted")

def test_reports_missing_git():
    with tempfile.TemporaryDirectory() as tmpdir:
        env = {'PATH': '/nonexistent'}
        result = subprocess.run(
            [sys.executable, str(GIT_HOOK), '--url', TEST_URL, '--snapshot-id', 'test123'],
            cwd=tmpdir, capture_output=True, text=True, env=env
        )
        if result.returncode != 0:
            combined = result.stdout + result.stderr
            assert 'DEPENDENCY_NEEDED' in combined or 'git' in combined.lower() or 'ERROR=' in combined

def test_handles_non_git_url():
    if not shutil.which('git'):
        pytest.skip("git not installed")

    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(GIT_HOOK), '--url', 'https://example.com', '--snapshot-id', 'test789'],
            cwd=tmpdir, capture_output=True, text=True, timeout=30
        )
        # Should fail or skip for non-git URL
        assert result.returncode in (0, 1)

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

        if result_json:
            # Should report failure or skip for non-git URL
            assert result_json['status'] in ['failed', 'skipped'], f"Should fail or skip: {result_json}"

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
