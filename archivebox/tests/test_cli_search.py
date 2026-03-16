#!/usr/bin/env python3
"""
Tests for archivebox search command.
Verify search queries snapshots from DB.
"""

import json
import os
import subprocess


def test_search_finds_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that search command finds matching snapshots."""
    os.chdir(tmp_path)

    # Add snapshots
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Search for it
    result = subprocess.run(
        ['archivebox', 'search', 'example'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert 'example' in result.stdout


def test_search_returns_no_results_for_missing_term(tmp_path, process, disable_extractors_dict):
    """Test search returns empty for non-existent term."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'search', 'nonexistentterm12345'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Should complete with no results
    assert result.returncode in [0, 1]


def test_search_on_empty_archive(tmp_path, process):
    """Test search works on empty archive."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'search', 'anything'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Should complete without error
    assert result.returncode in [0, 1]


def test_search_json_outputs_matching_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that search --json returns parseable matching snapshot rows."""
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        check=True,
    )

    result = subprocess.run(
        ['archivebox', 'search', '--json'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert any('example.com' in row.get('url', '') for row in payload)


def test_search_json_with_headers_wraps_links_payload(tmp_path, process, disable_extractors_dict):
    """Test that search --json --with-headers returns a headers envelope."""
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        check=True,
    )

    result = subprocess.run(
        ['archivebox', 'search', '--json', '--with-headers'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    links = payload.get('links', payload)
    assert any('example.com' in row.get('url', '') for row in links)


def test_search_html_outputs_markup(tmp_path, process, disable_extractors_dict):
    """Test that search --html renders an HTML response."""
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        check=True,
    )

    result = subprocess.run(
        ['archivebox', 'search', '--html'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert '<' in result.stdout


def test_search_csv_outputs_requested_column(tmp_path, process, disable_extractors_dict):
    """Test that search --csv emits the requested fields."""
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        check=True,
    )

    result = subprocess.run(
        ['archivebox', 'search', '--csv', 'url', '--with-headers'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert 'url' in result.stdout
    assert 'example.com' in result.stdout


def test_search_with_headers_requires_structured_output_format(tmp_path, process):
    """Test that --with-headers is rejected without --json, --html, or --csv."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'search', '--with-headers'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert 'requires' in result.stderr.lower() or 'json' in result.stderr.lower()


def test_search_sort_option_runs_successfully(tmp_path, process, disable_extractors_dict):
    """Test that search --sort accepts sortable fields."""
    os.chdir(tmp_path)
    for url in ['https://iana.org', 'https://example.com']:
        subprocess.run(
            ['archivebox', 'add', '--index-only', '--depth=0', url],
            capture_output=True,
            env=disable_extractors_dict,
            check=True,
        )

    result = subprocess.run(
        ['archivebox', 'search', '--csv', 'url', '--sort=url'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert 'example.com' in result.stdout or 'iana.org' in result.stdout


def test_search_help_lists_supported_filters(tmp_path, process):
    """Test that search --help documents the available filters and output modes."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'search', '--help'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert '--filter-type' in result.stdout or '-f' in result.stdout
    assert '--status' in result.stdout
    assert '--sort' in result.stdout
