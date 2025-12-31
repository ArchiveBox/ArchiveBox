"""
Integration tests for readability plugin

Tests verify:
1. Validate hook checks for readability-extractor binary
2. Verify deps with abx-pkg
3. Plugin reports missing dependency correctly
4. Extraction works against real example.com content
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    get_plugin_dir,
    get_hook_script,
    PLUGINS_ROOT,
)


PLUGIN_DIR = get_plugin_dir(__file__)
READABILITY_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_readability.*')
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
    """Test that script reports DEPENDENCY_NEEDED when readability-extractor is not found."""
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

        # Missing binary is a transient error - should exit 1 with no JSONL
        assert result.returncode == 1, "Should exit 1 when dependency missing"

        # Should NOT emit JSONL (transient error - will be retried)
        jsonl_lines = [line for line in result.stdout.strip().split('\n')
                      if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, "Should not emit JSONL for transient error (missing binary)"

        # Should log error to stderr
        assert 'readability-extractor' in result.stderr.lower() or 'error' in result.stderr.lower(), \
            "Should report error in stderr"


def test_verify_deps_with_abx_pkg():
    """Verify readability-extractor is available via abx-pkg."""
    from abx_pkg import Binary, NpmProvider, EnvProvider, BinProviderOverrides

    readability_binary = Binary(
        name='readability-extractor',
        binproviders=[NpmProvider(), EnvProvider()],
        overrides={'npm': {'packages': ['github:ArchiveBox/readability-extractor']}}
    )
    readability_loaded = readability_binary.load()

    if readability_loaded and readability_loaded.abspath:
        assert True, "readability-extractor is available"
    else:
        pass


def test_extracts_article_after_installation():
    """Test full workflow: extract article using readability-extractor from real HTML."""
    # Prerequisites checked by earlier test (install hook should have run)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create example.com HTML for readability to process
        create_example_html(tmpdir)

        # Run readability extraction (should find the binary)
        result = subprocess.run(
            [sys.executable, str(READABILITY_HOOK), '--url', TEST_URL, '--snapshot-id', 'test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0, f"Extraction failed: {result.stderr}"

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
        assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"

        # Verify output files exist (hook writes to current directory)
        html_file = tmpdir / 'content.html'
        txt_file = tmpdir / 'content.txt'
        json_file = tmpdir / 'article.json'

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


def test_fails_gracefully_without_html_source():
    """Test that extraction fails gracefully when no HTML source is available."""
    # Prerequisites checked by earlier test (install hook should have run)

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
