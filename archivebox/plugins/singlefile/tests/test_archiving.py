"""
Integration tests - archive example.com with SingleFile and verify output
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_SCRIPT = PLUGIN_DIR / "on_Snapshot__04_singlefile.js"
TEST_URL = "https://example.com"


# Check if single-file CLI is available
try:
    result = subprocess.run(
        ["which", "single-file"],
        capture_output=True,
        timeout=5
    )
    SINGLEFILE_CLI_AVAILABLE = result.returncode == 0
except:
    SINGLEFILE_CLI_AVAILABLE = False


@pytest.mark.skipif(
    not SINGLEFILE_CLI_AVAILABLE,
    reason="single-file CLI not installed (npm install -g single-file-cli)"
)
def test_archives_example_com():
    """Archive example.com and verify output contains expected content"""

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "singlefile"
        output_dir.mkdir()

        output_file = output_dir / "singlefile.html"

        # Run single-file CLI
        result = subprocess.run(
            [
                "single-file",
                "--browser-headless",
                TEST_URL,
                str(output_file)
            ],
            capture_output=True,
            text=True,
            timeout=120
        )

        assert result.returncode == 0, f"Archive failed: {result.stderr}"

        # Verify output exists
        assert output_file.exists(), "Output file not created"

        # Read and verify content
        html_content = output_file.read_text()
        file_size = output_file.stat().st_size

        # Should be substantial (embedded resources)
        assert file_size > 900, f"Output too small: {file_size} bytes"

        # Verify HTML structure (SingleFile minifies, so <head> tag may be omitted)
        assert "<html" in html_content.lower()
        assert "<body" in html_content.lower()
        assert "<title>" in html_content.lower() or "title>" in html_content.lower()

        # Verify example.com content is actually present
        assert "example domain" in html_content.lower(), "Missing 'Example Domain' title"
        assert "this domain is" in html_content.lower(), "Missing example.com description text"
        assert "iana.org" in html_content.lower(), "Missing IANA link"

        # Verify it's not just empty/error page
        assert file_size > 900, f"File too small: {file_size} bytes"


@pytest.mark.skipif(not SINGLEFILE_CLI_AVAILABLE, reason="single-file CLI not installed")
def test_different_urls_produce_different_outputs():
    """Verify different URLs produce different archived content"""

    with tempfile.TemporaryDirectory() as tmpdir:
        outputs = {}

        for url in ["https://example.com", "https://example.org"]:
            output_file = Path(tmpdir) / f"{url.replace('https://', '').replace('.', '_')}.html"

            result = subprocess.run(
                ["single-file", "--browser-headless", url, str(output_file)],
                capture_output=True,
                timeout=120
            )

            if result.returncode == 0 and output_file.exists():
                outputs[url] = output_file.read_text()

        assert len(outputs) == 2, "Should archive both URLs"

        # Verify outputs differ
        urls = list(outputs.keys())
        assert outputs[urls[0]] != outputs[urls[1]], "Different URLs should produce different outputs"

        # Each should contain its domain
        assert "example.com" in outputs[urls[0]]
        assert "example.org" in outputs[urls[1]]
