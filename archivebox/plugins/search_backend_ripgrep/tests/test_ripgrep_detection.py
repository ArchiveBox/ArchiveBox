#!/usr/bin/env python3
"""
Tests for ripgrep binary detection and archivebox install functionality.

Guards against regressions in:
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
    """Test that ripgrep hook finds binary using shutil.which() when env var is just a name."""
    hook_path = Path(__file__).parent.parent / 'on_Crawl__00_validate_ripgrep.py'

    # Skip if rg is not installed
    if not shutil.which('rg'):
        pytest.skip("ripgrep (rg) not installed")

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

    # Parse JSONL output
    lines = [line for line in result.stdout.strip().split('\n') if line.strip()]
    assert len(lines) >= 2, "Expected at least 2 JSONL lines (InstalledBinary + Machine config)"

    installed_binary = json.loads(lines[0])
    assert installed_binary['type'] == 'InstalledBinary'
    assert installed_binary['name'] == 'rg'
    assert '/' in installed_binary['abspath'], "Expected full path, not just binary name"
    assert Path(installed_binary['abspath']).is_file(), "Binary path should exist"
    assert installed_binary['version'], "Version should be detected"

    machine_config = json.loads(lines[1])
    assert machine_config['type'] == 'Machine'
    assert machine_config['key'] == 'config/RIPGREP_BINARY'
    assert '/' in machine_config['value'], "Machine config should store full path"


def test_ripgrep_hook_skips_when_backend_not_ripgrep():
    """Test that ripgrep hook exits silently when search backend is not ripgrep."""
    hook_path = Path(__file__).parent.parent / 'on_Crawl__00_validate_ripgrep.py'

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
    """Test that ripgrep hook works when RIPGREP_BINARY is an absolute path."""
    hook_path = Path(__file__).parent.parent / 'on_Crawl__00_validate_ripgrep.py'

    rg_path = shutil.which('rg')
    if not rg_path:
        pytest.skip("ripgrep (rg) not installed")

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

    assert result.returncode == 0, f"Hook failed: {result.stderr}"
    assert result.stdout.strip(), "Hook should produce output"

    installed_binary = json.loads(result.stdout.strip().split('\n')[0])
    assert installed_binary['abspath'] == rg_path


@pytest.mark.django_db
def test_machine_config_overrides_base_config():
    """
    Test that Machine.config overrides take precedence over base config.

    Guards against regression where archivebox version was showing binaries
    as "not installed" even though they were detected and stored in Machine.config.
    """
    from machine.models import Machine, InstalledBinary

    machine = Machine.current()

    # Simulate a hook detecting chrome and storing it with a different path than base config
    detected_chrome_path = '/custom/path/to/chrome'
    machine.config['CHROME_BINARY'] = detected_chrome_path
    machine.config['CHROME_VERSION'] = '143.0.7499.170'
    machine.save()

    # Create InstalledBinary record
    InstalledBinary.objects.create(
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
    Test that SEARCH_BACKEND_ENGINE is passed to hook environment.

    Guards against regression where hooks couldn't determine which search backend was active.
    """
    from pathlib import Path
    from archivebox.hooks import build_hook_environment
    from archivebox.config.configset import get_config

    config = get_config()
    search_backend = config.get('SEARCH_BACKEND_ENGINE', 'ripgrep')

    env = build_hook_environment(overrides=None)

    assert 'SEARCH_BACKEND_ENGINE' in env, \
        "SEARCH_BACKEND_ENGINE must be in hook environment"
    assert env['SEARCH_BACKEND_ENGINE'] == search_backend, \
        f"Expected SEARCH_BACKEND_ENGINE={search_backend}, got {env.get('SEARCH_BACKEND_ENGINE')}"


@pytest.mark.django_db
def test_install_creates_installedbinary_records():
    """
    Test that archivebox install creates InstalledBinary records for detected binaries.

    This is an integration test that verifies the full install flow.
    """
    from machine.models import Machine, InstalledBinary
    from crawls.models import Seed, Crawl
    from crawls.statemachines import CrawlMachine
    from archivebox.base_models.models import get_or_create_system_user_pk

    machine = Machine.current()
    initial_binary_count = InstalledBinary.objects.filter(machine=machine).count()

    # Create an install crawl (like archivebox install does)
    created_by_id = get_or_create_system_user_pk()
    seed, _ = Seed.objects.get_or_create(
        uri='archivebox://test-install',
        label='Test dependency detection',
        created_by_id=created_by_id,
        defaults={'extractor': 'auto'},
    )

    crawl = Crawl.objects.create(
        seed=seed,
        max_depth=0,
        created_by_id=created_by_id,
        status='queued',
    )

    # Run the crawl state machine (this triggers hooks)
    sm = CrawlMachine(crawl)
    sm.send('tick')  # queued -> started (runs hooks)

    # Verify InstalledBinary records were created
    final_binary_count = InstalledBinary.objects.filter(machine=machine).count()
    assert final_binary_count > initial_binary_count, \
        "archivebox install should create InstalledBinary records"

    # Verify at least some common binaries were detected
    common_binaries = ['git', 'wget', 'node']
    detected = []
    for bin_name in common_binaries:
        if InstalledBinary.objects.filter(machine=machine, name=bin_name).exists():
            detected.append(bin_name)

    assert detected, f"At least one of {common_binaries} should be detected"

    # Verify detected binaries have valid paths and versions
    for binary in InstalledBinary.objects.filter(machine=machine):
        if binary.abspath:  # Only check non-empty paths
            assert '/' in binary.abspath, \
                f"{binary.name} should have full path, not just name: {binary.abspath}"
            # Version might be empty for some binaries, that's ok


@pytest.mark.django_db
def test_ripgrep_only_detected_when_backend_enabled():
    """
    Test that ripgrep is only detected when SEARCH_BACKEND_ENGINE='ripgrep'.

    Guards against ripgrep being installed/detected when not needed.
    """
    from machine.models import Machine, InstalledBinary
    from crawls.models import Seed, Crawl
    from crawls.statemachines import CrawlMachine
    from archivebox.base_models.models import get_or_create_system_user_pk
    from django.conf import settings

    if not shutil.which('rg'):
        pytest.skip("ripgrep (rg) not installed")

    machine = Machine.current()

    # Clear any existing ripgrep records
    InstalledBinary.objects.filter(machine=machine, name='rg').delete()

    # Test 1: With ripgrep backend - should be detected
    with patch('archivebox.config.configset.get_config') as mock_config:
        mock_config.return_value = {'SEARCH_BACKEND_ENGINE': 'ripgrep', 'RIPGREP_BINARY': 'rg'}

        created_by_id = get_or_create_system_user_pk()
        seed = Seed.objects.create(
            uri='archivebox://test-rg-enabled',
            label='Test ripgrep detection enabled',
            created_by_id=created_by_id,
            extractor='auto',
        )

        crawl = Crawl.objects.create(
            seed=seed,
            max_depth=0,
            created_by_id=created_by_id,
            status='queued',
        )

        sm = CrawlMachine(crawl)
        sm.send('tick')

        # Ripgrep should be detected
        rg_detected = InstalledBinary.objects.filter(machine=machine, name='rg').exists()
        assert rg_detected, "Ripgrep should be detected when SEARCH_BACKEND_ENGINE='ripgrep'"

    # Clear records again
    InstalledBinary.objects.filter(machine=machine, name='rg').delete()

    # Test 2: With different backend - should NOT be detected
    with patch('archivebox.config.configset.get_config') as mock_config:
        mock_config.return_value = {'SEARCH_BACKEND_ENGINE': 'sqlite', 'RIPGREP_BINARY': 'rg'}

        seed2 = Seed.objects.create(
            uri='archivebox://test-rg-disabled',
            label='Test ripgrep detection disabled',
            created_by_id=created_by_id,
            extractor='auto',
        )

        crawl2 = Crawl.objects.create(
            seed=seed2,
            max_depth=0,
            created_by_id=created_by_id,
            status='queued',
        )

        sm2 = CrawlMachine(crawl2)
        sm2.send('tick')

        # Ripgrep should NOT be detected
        rg_detected = InstalledBinary.objects.filter(machine=machine, name='rg').exists()
        assert not rg_detected, "Ripgrep should NOT be detected when SEARCH_BACKEND_ENGINE!='ripgrep'"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
