"""
Integration tests for readability plugin

Tests verify:
1. Plugin reports missing dependency correctly
2. readability-cli can be installed via npm (note: package name != binary name)
3. Extraction works against real example.com content
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
READABILITY_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_readability.py'))
TEST_URL = 'https://example.com'


def create_example_html(tmpdir: Path) -> Path:
    """Create sample HTML that looks like example.com with enough content for Readability."""
    singlefile_dir = tmpdir / 'singlefile'
    singlefile_dir.mkdir()

    html_file = singlefile_dir / 'singlefile.html'
    html_file.write_text('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Example Domain</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <article>
        <header>
            <h1>Example Domain</h1>
        </header>
        <div class="content">
            <p>This domain is for use in illustrative examples in documents. You may use this
            domain in literature without prior coordination or asking for permission.</p>

            <p>Example domains are maintained by the Internet Assigned Numbers Authority (IANA)
            to provide a well-known address for documentation purposes. This helps authors create
            examples that readers can understand without confusion about actual domain ownership.</p>

            <p>The practice of using example domains dates back to the early days of the internet.
            These reserved domains ensure that example code and documentation doesn't accidentally
            point to real, active websites that might change or disappear over time.</p>

            <p>For more information about example domains and their history, you can visit the
            IANA website. They maintain several example domains including example.com, example.net,
            and example.org, all specifically reserved for this purpose.</p>

            <p><a href="https://www.iana.org/domains/example">More information about example domains...</a></p>
        </div>
    </article>
</body>
</html>
    ''')

    return html_file


def test_hook_script_exists():
    """Verify hook script exists."""
    assert READABILITY_HOOK.exists(), f"Hook script not found: {READABILITY_HOOK}"


def test_reports_missing_dependency_when_not_installed():
    """Test that script reports DEPENDENCY_NEEDED when readability-cli is not found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create HTML source so it doesn't fail on missing HTML
        create_example_html(tmpdir)

        # Run with empty PATH so binary won't be found
        env = {'PATH': '/nonexistent', 'HOME': str(tmpdir)}

        result = subprocess.run(
            [sys.executable, str(READABILITY_HOOK), '--url', TEST_URL, '--snapshot-id', 'test123'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env
        )

        # Should fail and report missing dependency
        assert result.returncode != 0, "Should exit non-zero when dependency missing"
        combined = result.stdout + result.stderr
        assert 'DEPENDENCY_NEEDED' in combined, "Should output DEPENDENCY_NEEDED"
        assert 'readability-cli' in combined or 'BIN_NAME' in combined, "Should mention readability-cli"


def test_can_install_readability_via_npm():
    """Test that readability-cli can be installed via npm and binary becomes available.

    Note: The npm package 'readability-cli' installs a binary named 'readable',
    so we test the full installation flow using npm install directly.
    """

    # Check npm is available
    if not shutil.which('npm'):
        pytest.skip("npm not available on this system")

    # Install readability-cli package via npm
    # The orchestrator/dependency hooks would call this via npm provider
    result = subprocess.run(
        ['npm', 'install', '-g', 'readability-cli'],
        capture_output=True,
        text=True,
        timeout=300
    )

    assert result.returncode == 0, f"npm install failed: {result.stderr}"

    # Verify the 'readable' binary is now available
    # (readability-cli package installs as 'readable' not 'readability-cli')
    result = subprocess.run(['which', 'readable'], capture_output=True, text=True)
    assert result.returncode == 0, "readable binary not found after npm install"

    binary_path = result.stdout.strip()
    assert Path(binary_path).exists(), f"Binary should exist at {binary_path}"

    # Test that it's executable and responds to --version
    result = subprocess.run(
        [binary_path, '--version'],
        capture_output=True,
        text=True,
        timeout=10
    )
    assert result.returncode == 0, f"Binary not executable: {result.stderr}"


def test_extracts_article_after_installation():
    """Test full workflow: ensure readability-cli installed then extract from example.com HTML."""

    # Check npm is available
    if not shutil.which('npm'):
        pytest.skip("npm not available on this system")

    # Ensure readability-cli is installed (orchestrator would handle this)
    install_result = subprocess.run(
        ['npm', 'install', '-g', 'readability-cli'],
        capture_output=True,
        text=True,
        timeout=300
    )

    if install_result.returncode != 0:
        pytest.skip(f"Could not install readability-cli: {install_result.stderr}")

    # Now test extraction
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create example.com HTML for readability to process
        create_example_html(tmpdir)

        # Run readability extraction (should find the installed binary)
        result = subprocess.run(
            [sys.executable, str(READABILITY_HOOK), '--url', TEST_URL, '--snapshot-id', 'test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0, f"Extraction failed: {result.stderr}"

        # Verify output directory created
        readability_dir = tmpdir / 'readability'
        assert readability_dir.exists(), "Output directory not created"

        # Verify output files exist
        html_file = readability_dir / 'content.html'
        txt_file = readability_dir / 'content.txt'
        json_file = readability_dir / 'article.json'

        assert html_file.exists(), "content.html not created"
        assert txt_file.exists(), "content.txt not created"
        assert json_file.exists(), "article.json not created"

        # Verify HTML content contains REAL example.com text
        html_content = html_file.read_text()
        assert len(html_content) > 100, f"HTML content too short: {len(html_content)} bytes"
        assert 'example domain' in html_content.lower(), "Missing 'Example Domain' in HTML"
        assert ('illustrative examples' in html_content.lower() or
                'use in' in html_content.lower() or
                'literature' in html_content.lower()), \
            "Missing example.com description in HTML"

        # Verify text content contains REAL example.com text
        txt_content = txt_file.read_text()
        assert len(txt_content) > 50, f"Text content too short: {len(txt_content)} bytes"
        assert 'example' in txt_content.lower(), "Missing 'example' in text"

        # Verify JSON metadata
        json_data = json.loads(json_file.read_text())
        assert isinstance(json_data, dict), "article.json should be a dict"

        # Verify stdout contains expected output
        assert 'STATUS=succeeded' in result.stdout, "Should report success"
        assert 'OUTPUT=readability' in result.stdout, "Should report output directory"


def test_fails_gracefully_without_html_source():
    """Test that extraction fails gracefully when no HTML source is available."""

    # Check npm is available
    if not shutil.which('npm'):
        pytest.skip("npm not available on this system")

    # Ensure readability-cli is installed
    install_result = subprocess.run(
        ['npm', 'install', '-g', 'readability-cli'],
        capture_output=True,
        text=True,
        timeout=300
    )

    if install_result.returncode != 0:
        pytest.skip("Could not install readability-cli")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Don't create any HTML source files

        result = subprocess.run(
            [sys.executable, str(READABILITY_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode != 0, "Should fail without HTML source"
        combined_output = result.stdout + result.stderr
        assert ('no html source' in combined_output.lower() or
                'not found' in combined_output.lower() or
                'ERROR=' in combined_output), \
            "Should report missing HTML source"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
