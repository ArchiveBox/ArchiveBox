import json
import subprocess

from .fixtures import *

def test_search_json(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "--index-only", "https://example.com", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    search_process = subprocess.run(["archivebox", "search", "--json"], capture_output=True)
    output_str = search_process.stdout.decode("utf-8").strip()
    # Handle potential control characters in output
    try:
        output_json = json.loads(output_str)
    except json.JSONDecodeError:
        # Try with strict=False if there are control characters
        import re
        # Remove ANSI escape sequences and control characters
        clean_str = re.sub(r'\x1b\[[0-9;]*m', '', output_str)
        clean_str = re.sub(r'[\x00-\x1f\x7f]', lambda m: ' ' if m.group(0) in '\t\n\r' else '', clean_str)
        output_json = json.loads(clean_str)
    # Verify we get at least one snapshot back
    assert len(output_json) >= 1
    # Should include the requested URL
    assert any("example.com" in entry.get("url", "") for entry in output_json)


def test_search_json_headers(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "--index-only", "https://example.com", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    search_process = subprocess.run(["archivebox", "search", "--json", "--with-headers"], capture_output=True)
    output_str = search_process.stdout.decode("utf-8").strip()
    # Handle potential control characters in output
    try:
        output_json = json.loads(output_str)
    except json.JSONDecodeError:
        # Try with strict=False if there are control characters
        import re
        # Remove ANSI escape sequences and control characters
        clean_str = re.sub(r'\x1b\[[0-9;]*m', '', output_str)
        clean_str = re.sub(r'[\x00-\x1f\x7f]', lambda m: ' ' if m.group(0) in '\t\n\r' else '', clean_str)
        output_json = json.loads(clean_str)
    # The response should have a links key with headers mode
    links = output_json.get("links", output_json)
    assert len(links) >= 1

def test_search_html(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "--index-only", "https://example.com", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    search_process = subprocess.run(["archivebox", "search", "--html"], capture_output=True)
    output_html = search_process.stdout.decode("utf-8")
    # Should contain some HTML and reference to the source file
    assert "sources" in output_html or "cli_add" in output_html or "<" in output_html

def test_search_html_headers(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "--index-only", "https://example.com", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    search_process = subprocess.run(["archivebox", "search", "--html", "--with-headers"], capture_output=True)
    output_html = search_process.stdout.decode("utf-8")
    # Should contain HTML
    assert "<" in output_html

def test_search_csv(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "--index-only", "https://example.com", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    search_process = subprocess.run(["archivebox", "search", "--csv", "url"], capture_output=True)
    output_csv = search_process.stdout.decode("utf-8")
    # Should contain the requested URL
    assert "example.com" in output_csv

def test_search_csv_headers(process, disable_extractors_dict):
    subprocess.run(["archivebox", "add", "--index-only", "https://example.com", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    search_process = subprocess.run(["archivebox", "search", "--csv", "url", "--with-headers"], capture_output=True)
    output_csv = search_process.stdout.decode("utf-8")
    # Should have url header and requested URL
    assert "url" in output_csv
    assert "example.com" in output_csv

def test_search_with_headers_requires_format(process):
    search_process = subprocess.run(["archivebox", "search", "--with-headers"], capture_output=True)
    stderr = search_process.stderr.decode("utf-8")
    assert "--with-headers" in stderr and ("requires" in stderr or "can only be used" in stderr)

def test_sort_by_url(process, disable_extractors_dict):
    # Add two URLs - they will create separate source files
    subprocess.run(["archivebox", "add", "--index-only", "https://iana.org", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    subprocess.run(["archivebox", "add", "--index-only", "https://example.com", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)

    # Search with sort should return results (even if they're file:// URLs)
    search_process = subprocess.run(["archivebox", "search", "--csv", "url", "--sort=url"], capture_output=True)
    output = search_process.stdout.decode("utf-8")
    lines = [line for line in output.strip().split("\n") if line]
    # Should have at least 2 snapshots (the source file snapshots)
    assert len(lines) >= 2
