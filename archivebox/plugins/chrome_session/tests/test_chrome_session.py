"""
Integration tests for chrome_session plugin

Tests verify:
1. Validate hook checks for Chrome/Chromium binary
2. Verify deps with abx-pkg
3. Chrome session script exists
"""

import json
import subprocess
import sys
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
CHROME_VALIDATE_HOOK = PLUGIN_DIR / 'on_Crawl__00_validate_chrome.py'
CHROME_SESSION_HOOK = PLUGIN_DIR / 'on_Snapshot__20_chrome_session.js'


def test_hook_script_exists():
    """Verify chrome session hook exists."""
    assert CHROME_SESSION_HOOK.exists(), f"Hook not found: {CHROME_SESSION_HOOK}"


def test_chrome_validate_hook():
    """Test chrome validate hook checks for Chrome/Chromium binary."""
    result = subprocess.run(
        [sys.executable, str(CHROME_VALIDATE_HOOK)],
        capture_output=True,
        text=True,
        timeout=30
    )

    # Hook exits 0 if binary found, 1 if not found (with Dependency record)
    if result.returncode == 0:
        # Binary found - verify InstalledBinary JSONL output
        found_binary = False
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    record = json.loads(line)
                    if record.get('type') == 'InstalledBinary':
                        assert record['name'] == 'chrome'
                        assert record['abspath']
                        assert Path(record['abspath']).exists(), f"Chrome binary should exist at {record['abspath']}"
                        found_binary = True
                        break
                except json.JSONDecodeError:
                    pass
        assert found_binary, "Should output InstalledBinary record when binary found"
    else:
        # Binary not found - verify Dependency JSONL output
        found_dependency = False
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    record = json.loads(line)
                    if record.get('type') == 'Dependency':
                        assert record['bin_name'] == 'chrome'
                        found_dependency = True
                        break
                except json.JSONDecodeError:
                    pass
        assert found_dependency, "Should output Dependency record when binary not found"


def test_verify_deps_with_abx_pkg():
    """Verify chrome is available via abx-pkg."""
    from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider, BinProviderOverrides

    AptProvider.model_rebuild()
    BrewProvider.model_rebuild()
    EnvProvider.model_rebuild()

    # Try various chrome binary names
    for binary_name in ['chromium', 'chromium-browser', 'google-chrome', 'chrome']:
        try:
            chrome_binary = Binary(
                name=binary_name,
                binproviders=[AptProvider(), BrewProvider(), EnvProvider()]
            )
            chrome_loaded = chrome_binary.load()
            if chrome_loaded and chrome_loaded.abspath:
                # Found at least one chrome variant
                assert Path(chrome_loaded.abspath).exists()
                return
        except Exception:
            continue

    # If we get here, chrome not available
    import shutil
    if not (shutil.which('chromium') or shutil.which('chrome') or shutil.which('google-chrome')):
        pytest.skip("Chrome/Chromium not available - Dependency record should have been emitted")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
