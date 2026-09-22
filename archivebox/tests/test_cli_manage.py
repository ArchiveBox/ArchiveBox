#!/usr/bin/env python3
"""
Tests for archivebox manage command.
Verify manage command runs Django management commands.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_manage_help_works(initialized_archive):
    """Test that manage help command works."""

    result = run_archivebox_cmd(
        ["manage", "help"],
        timeout=30,
    )

    assert result.returncode == 0
    assert len(result.stdout) > 100


def test_manage_showmigrations_works(initialized_archive):
    """Test that manage showmigrations works."""

    result = run_archivebox_cmd(
        ["manage", "showmigrations"],
        timeout=30,
    )

    assert result.returncode == 0
    # Should show migration status
    assert "core" in result.stdout or "[" in result.stdout


def test_manage_dbshell_command_exists(initialized_archive):
    """Test that manage dbshell command is recognized."""

    result = run_archivebox_cmd(
        ["manage", "help", "dbshell"],
        timeout=30,
    )

    # Should show help for dbshell
    assert result.returncode == 0
    assert "dbshell" in result.stdout or "database" in result.stdout.lower()


def test_manage_check_works(initialized_archive):
    """Test that manage check works."""

    result = run_archivebox_cmd(
        ["manage", "check"],
        timeout=30,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "System check identified no issues" in result.stdout


def test_manage_noninteractive_createsuperuser_does_not_request_docker_tty(initialized_archive):
    result = run_archivebox_cmd(
        [
            "manage",
            "createsuperuser",
            "--noinput",
            "--username",
            "noninteractive-admin",
            "--email",
            "admin@example.com",
        ],
        env={
            "IN_DOCKER": "True",
            "DJANGO_SUPERUSER_PASSWORD": "test-password",
        },
        timeout=30,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "need to pass -it" not in result.stderr
