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


def test_manage_changepassword_piped_input_and_eof(initialized_archive):
    username = "password-input-admin"
    password = "Local-password-input-63491!"
    created = run_archivebox_cmd(
        ["manage", "createsuperuser", "--noinput", "--username", username, "--email", "local@example.invalid"],
        env={"DJANGO_SUPERUSER_PASSWORD": "Original-local-password-63491!"},
    )
    assert created.returncode == 0, created.stderr
    changed = run_archivebox_cmd(
        ["manage", "changepassword", username],
        input=f"{password}\n{password}\n",
        start_new_session=True,
    )
    assert changed.returncode == 0, changed.stderr
    assert "Password changed successfully" in changed.stdout
    verified = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            "import os; from django.contrib.auth import get_user_model; "
            "assert get_user_model().objects.get(username='password-input-admin').check_password(os.environ['LOCAL_TEST_PASSWORD'])",
        ],
        env={"LOCAL_TEST_PASSWORD": password},
    )
    assert verified.returncode == 0, verified.stderr
    for incomplete_input in ("", f"{password}\n"):
        ended = run_archivebox_cmd(
            ["manage", "changepassword", username],
            input=incomplete_input,
            start_new_session=True,
        )
        assert ended.returncode == 1
        assert "Password input ended before both passwords were received" in ended.stderr
        assert "Got CTRL+C" not in ended.stderr
