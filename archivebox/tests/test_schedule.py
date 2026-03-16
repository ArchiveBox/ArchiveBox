#!/usr/bin/env python3
"""Integration tests for archivebox schedule command."""

import os
import subprocess

import pytest

from .fixtures import process, disable_extractors_dict


def test_schedule_show_lists_jobs(tmp_path, process):
    """Test that --show lists current scheduled jobs."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'schedule', '--show'],
        capture_output=True,
        text=True,
    )

    # Should either show jobs or indicate no jobs
    assert 'no' in result.stdout.lower() or 'archivebox' in result.stdout.lower() or result.returncode == 0


def test_schedule_clear_removes_jobs(tmp_path, process):
    """Test that --clear removes scheduled jobs."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'schedule', '--clear'],
        capture_output=True,
        text=True,
    )

    # Should complete successfully (may have no jobs to clear)
    assert result.returncode == 0


def test_schedule_every_requires_valid_period(tmp_path, process):
    """Test that --every requires valid time period."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'schedule', '--every=invalid_period', 'https://example.com/feed.xml'],
        capture_output=True,
        text=True,
    )

    # Should fail with invalid period
    assert result.returncode != 0 or 'invalid' in result.stdout.lower()


class TestScheduleCLI:
    """Test the CLI interface for schedule command."""

    def test_cli_help(self, tmp_path, process):
        """Test that --help works for schedule command."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'schedule', '--help'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert '--every' in result.stdout
        assert '--show' in result.stdout
        assert '--clear' in result.stdout
        assert '--depth' in result.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
