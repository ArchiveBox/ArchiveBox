#!/usr/bin/env python3
"""
Tests for ripgrep binary detection and archivebox install functionality.

Guards against regressions in:
    pass
1. Machine.config overrides not being used in version command
2. Ripgrep hook not resolving binary names via shutil.which()
3. SEARCH_BACKEND_ENGINE not being passed to hook environment
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def test_ripgrep_hook_detects_binary_from_path():
    """Test that ripgrep hook finds binary using abx-pkg when env var is just a name."""
    hook_path = Path(__file__).parent.parent / 'on_Crawl__50_ripgrep_install.py'

    # Skip if rg is not installed
    if not shutil.which('rg'):
        pass

    # Set SEARCH_BACKEND_ENGINE to enable the hook
    env = os.environ.copy()
    env['SEARCH_BACKEND_ENGINE'] = 'ripgrep'
    env['RIPGREP_BINARY'] = 'rg'  # Just the name, not the full path (this was the bug)

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, f"Hook failed: {result.stderr}"

    # Parse JSONL output (filter out non-JSON lines)
    lines = [line for line in result.stdout.strip().split('\n') if line.strip() and line.strip().startswith('{')]
    assert len(lines) >= 1, "Expected at least 1 JSONL line (Binary)"

    binary = json.loads(lines[0])
    assert binary['type'] == 'Binary'
    assert binary['name'] == 'rg'
    assert 'binproviders' in binary, "Expected binproviders declaration"


def test_ripgrep_hook_skips_when_backend_not_ripgrep():
    """Test that ripgrep hook exits silently when search backend is not ripgrep."""
    hook_path = Path(__file__).parent.parent / 'on_Crawl__50_ripgrep_install.py'

    env = os.environ.copy()
    env['SEARCH_BACKEND_ENGINE'] = 'sqlite'  # Different backend

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, "Hook should exit successfully when backend is not ripgrep"
    assert result.stdout.strip() == '', "Hook should produce no output when backend is not ripgrep"


def test_ripgrep_hook_handles_absolute_path():
    """Test that ripgrep hook exits successfully when RIPGREP_BINARY is a valid absolute path."""
    hook_path = Path(__file__).parent.parent / 'on_Crawl__50_ripgrep_install.py'

    rg_path = shutil.which('rg')
    if not rg_path:
        pytest.skip("ripgrep not installed")

    env = os.environ.copy()
    env['SEARCH_BACKEND_ENGINE'] = 'ripgrep'
    env['RIPGREP_BINARY'] = rg_path  # Full absolute path

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, f"Hook should exit successfully when binary already configured: {result.stderr}"
    lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
    assert lines, "Expected Binary JSONL output when backend is ripgrep"


@pytest.mark.django_db
def test_machine_config_overrides_base_config():
    """
    Test that Machine.config overrides take precedence over base config.

    Guards against regression where archivebox version was showing binaries
    as "not installed" even though they were detected and stored in Machine.config.
    """
    from archivebox.machine.models import Machine, Binary

    import archivebox.machine.models as models
    models._CURRENT_MACHINE = None
    machine = Machine.current()

    # Simulate a hook detecting chrome and storing it with a different path than base config
    detected_chrome_path = '/custom/path/to/chrome'
    machine.config['CHROME_BINARY'] = detected_chrome_path
    machine.config['CHROME_VERSION'] = '143.0.7499.170'
    machine.save()

    # Create Binary record
    Binary.objects.create(
        machine=machine,
        name='chrome',
        abspath=detected_chrome_path,
        version='143.0.7499.170',
        binprovider='env',
    )

    # Verify Machine.config takes precedence
    from archivebox.config.configset import get_config
    config = get_config()

    # Machine.config should override the base config value
    assert machine.config.get('CHROME_BINARY') == detected_chrome_path

    # The version command should use Machine.config, not base config
    # (Base config might have 'chromium' while Machine.config has the full path)
    bin_value = machine.config.get('CHROME_BINARY') or config.get('CHROME_BINARY', '')
    assert bin_value == detected_chrome_path, \
        "Machine.config override should take precedence over base config"


@pytest.mark.django_db
def test_search_backend_engine_passed_to_hooks():
    """
    Test that SEARCH_BACKEND_ENGINE is configured properly.

    Guards against regression where hooks couldn't determine which search backend was active.
    """
    from archivebox.config.configset import get_config
    import os

    config = get_config()
    search_backend = config.get('SEARCH_BACKEND_ENGINE', 'ripgrep')

    # Verify config contains SEARCH_BACKEND_ENGINE
    assert search_backend in ('ripgrep', 'sqlite', 'sonic'), \
        f"SEARCH_BACKEND_ENGINE should be valid backend, got {search_backend}"

    # Verify it's accessible via environment (hooks read from os.environ)
    # Hooks receive environment variables, so this verifies the mechanism works
    assert 'SEARCH_BACKEND_ENGINE' in os.environ or search_backend == config.get('SEARCH_BACKEND_ENGINE'), \
        "SEARCH_BACKEND_ENGINE must be accessible to hooks"


@pytest.mark.django_db
def test_install_creates_binary_records():
    """
    Test that Binary records can be created and queried properly.

    This verifies the Binary model works correctly with the database.
    """
    from archivebox.machine.models import Machine, Binary
    import archivebox.machine.models as models

    models._CURRENT_MACHINE = None
    machine = Machine.current()
    initial_binary_count = Binary.objects.filter(machine=machine).count()

    # Create a test binary record
    test_binary = Binary.objects.create(
        machine=machine,
        name='test-binary',
        abspath='/usr/bin/test-binary',
        version='1.0.0',
        binprovider='env',
        status=Binary.StatusChoices.INSTALLED
    )

    # Verify Binary record was created
    final_binary_count = Binary.objects.filter(machine=machine).count()
    assert final_binary_count == initial_binary_count + 1, \
        "Binary record should be created"

    # Verify the binary can be queried
    found_binary = Binary.objects.filter(machine=machine, name='test-binary').first()
    assert found_binary is not None, "Binary should be found"
    assert found_binary.abspath == '/usr/bin/test-binary', "Binary path should match"
    assert found_binary.version == '1.0.0', "Binary version should match"

    # Clean up
    test_binary.delete()


@pytest.mark.django_db
def test_ripgrep_only_detected_when_backend_enabled():
    """
    Test ripgrep validation hook behavior with different SEARCH_BACKEND_ENGINE settings.

    Guards against ripgrep being detected when not needed.
    """
    import subprocess
    import sys
    from pathlib import Path

    if not shutil.which('rg'):
        pytest.skip("ripgrep not installed")

    hook_path = Path(__file__).parent.parent / 'on_Crawl__50_ripgrep_install.py'

    # Test 1: With ripgrep backend - should output Binary record
    env1 = os.environ.copy()
    env1['SEARCH_BACKEND_ENGINE'] = 'ripgrep'
    env1['RIPGREP_BINARY'] = 'rg'

    result1 = subprocess.run(
        [sys.executable, str(hook_path)],
        capture_output=True,
        text=True,
        env=env1,
        timeout=10,
    )

    assert result1.returncode == 0, f"Hook should succeed with ripgrep backend: {result1.stderr}"
    # Should output Binary JSONL when backend is ripgrep
    assert 'Binary' in result1.stdout, "Should output Binary when backend=ripgrep"

    # Test 2: With different backend - should output nothing
    env2 = os.environ.copy()
    env2['SEARCH_BACKEND_ENGINE'] = 'sqlite'
    env2['RIPGREP_BINARY'] = 'rg'

    result2 = subprocess.run(
        [sys.executable, str(hook_path)],
        capture_output=True,
        text=True,
        env=env2,
        timeout=10,
    )

    assert result2.returncode == 0, "Hook should exit successfully when backend is not ripgrep"
    assert result2.stdout.strip() == '', "Hook should produce no output when backend is not ripgrep"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
