"""
Integration tests for chrome_session plugin

Tests verify:
1. Install hook finds system Chrome or installs chromium
2. Verify deps with abx-pkg
3. Chrome session script exists
"""

import json
import subprocess
import sys
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
CHROME_INSTALL_HOOK = PLUGIN_DIR / 'on_Crawl__00_install_chrome.py'
CHROME_SESSION_HOOK = PLUGIN_DIR / 'on_Snapshot__20_chrome_session.js'


def test_hook_script_exists():
    """Verify chrome session hook exists."""
    assert CHROME_SESSION_HOOK.exists(), f"Hook not found: {CHROME_SESSION_HOOK}"


def test_chrome_install_hook():
    """Test chrome install hook to find or install Chrome/Chromium."""
    result = subprocess.run(
        [sys.executable, str(CHROME_INSTALL_HOOK)],
        capture_output=True,
        text=True,
        timeout=600
    )

    assert result.returncode == 0, f"Install hook failed: {result.stderr}"

    # Verify InstalledBinary JSONL output
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

    assert found_binary, "Should output InstalledBinary record"


def test_verify_deps_with_abx_pkg():
    """Verify chrome is available via abx-pkg after hook installation."""
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

    # If we get here, chrome should still be available from system
    import shutil
    assert shutil.which('chromium') or shutil.which('chrome') or shutil.which('google-chrome'), \
        "Chrome should be available after install hook"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
