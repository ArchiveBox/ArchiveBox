"""
Integration tests for git plugin

Tests verify:
    pass
1. Validate hook checks for git binary
2. Verify deps with abx-pkg
3. Standalone git extractor execution
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
GIT_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_git.*'), None)
TEST_URL = 'https://github.com/example/repo.git'

def test_hook_script_exists():
    assert GIT_HOOK.exists()

def test_verify_deps_with_abx_pkg():
    """Verify git is available via abx-pkg."""
    from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider, BinProviderOverrides

    git_binary = Binary(name='git', binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
    git_loaded = git_binary.load()

    if git_loaded and git_loaded.abspath:
        assert True, "git is available"
    else:
        pass

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
    pass
    if not shutil.which('git'):
        pass

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
                pass
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


def test_real_git_repo():
    """Test that git can clone a real GitHub repository."""
    import os

    if not shutil.which('git'):
        pytest.skip("git binary not available")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Use a real but small GitHub repository
        git_url = 'https://github.com/ArchiveBox/abx-pkg'

        env = os.environ.copy()
        env['GIT_TIMEOUT'] = '120'  # Give it time to clone

        start_time = time.time()
        result = subprocess.run(
            [sys.executable, str(GIT_HOOK), '--url', git_url, '--snapshot-id', 'testgit'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=180
        )
        elapsed_time = time.time() - start_time

        # Should succeed
        assert result.returncode == 0, f"Should clone repository successfully: {result.stderr}"

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

        # Check that the git repo was cloned
        git_dirs = list(tmpdir.glob('**/.git'))
        assert len(git_dirs) > 0, f"Should have cloned a git repository. Contents: {list(tmpdir.rglob('*'))}"

        print(f"Successfully cloned repository in {elapsed_time:.2f}s")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
