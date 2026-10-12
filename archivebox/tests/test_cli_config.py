#!/usr/bin/env python3
"""
Comprehensive tests for archivebox config command.
Verify config reads/writes ArchiveBox.conf file correctly.
"""

import json
import sqlite3
from archivebox.tests.conftest import run_archivebox_cmd, run_python_cwd
from archivebox.config.configset import read_ini_config
import pytest


@pytest.mark.parametrize("legacy", [False, True])
def test_secret_key_moves_to_db_without_invalidating_login(initialized_archive, legacy):
    config_file = initialized_archive / "ArchiveBox.conf"
    with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
        stored = [json.loads(row[0]) for row in db.execute("SELECT config FROM machine_machine")]
    legacy_key = next(config["SECRET_KEY"] for config in stored if config.get("_SECRET_KEY_DB"))
    assert legacy_key and "SECRET_KEY" not in config_file.read_text()
    setup = """
import django
django.setup()
from django.conf import settings
from django.test import Client
from django.contrib.auth import get_user_model
from archivebox.machine.models import Machine
client = Client(HTTP_HOST="admin.archivebox.localhost:5797")
"""
    stdout, stderr, code = run_python_cwd(
        setup
        + """
get_user_model().objects.create_superuser(username="secret-test", password="secret-test-password")
response = client.post("/admin/login/", {"username": "secret-test", "password": "secret-test-password", "next": "/admin/"})
assert response.status_code == 302, response.content
assert client.get("/admin/").wsgi_request.user.is_authenticated
print(client.cookies[settings.SESSION_COOKIE_NAME].value)
""",
        cwd=initialized_archive,
    )
    assert code == 0, stderr
    cookie = stdout.strip().splitlines()[-1]
    # Leave the real authenticated session in place but restore the legacy storage layout.
    if legacy:
        with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
            db.execute("UPDATE machine_machine SET config = '{}'")
        config_file.write_text(f"[SERVER_CONFIG]\nSECRET_KEY={legacy_key}\n")
    for args in (["config", "--set", "TIMEOUT=123"], ["init", "--quick"]):
        result = run_archivebox_cmd(args, cwd=initialized_archive)
        assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
        assert result.returncode == 0, result.stderr
        assert "SECRET_KEY" not in config_file.read_text()
        with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
            stored = [json.loads(row[0]) for row in db.execute("SELECT config FROM machine_machine")]
        adopted = [config for config in stored if config.get("_SECRET_KEY_DB")]
        assert adopted and all(config["SECRET_KEY"] == legacy_key for config in adopted)
        stdout, stderr, code = run_python_cwd(
            setup
            + f"""
assert settings.SECRET_KEY == {legacy_key!r}
client.cookies[settings.SESSION_COOKIE_NAME] = {cookie!r}
assert client.get("/admin/").wsgi_request.user.is_authenticated
machine = Machine.current()
machine.config = {{"TIMEOUT": 124}}
machine.save(update_fields=["config"])
assert machine.config["SECRET_KEY"] == settings.SECRET_KEY
""",
            cwd=initialized_archive,
        )
        assert code == 0, stderr
        with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
            db.execute("UPDATE machine_machine SET guid = 'previous-' || guid")


def test_secret_conversion_keeps_file_when_db_is_readonly_or_transaction_rolls_back(initialized_archive):
    config_file = initialized_archive / "ArchiveBox.conf"
    original = "[SERVER_CONFIG]\nSECRET_KEY=preserve-this-legacy-secret\n"
    for readonly in (True, False):
        with sqlite3.connect(initialized_archive / "index.sqlite3") as db:
            db.execute("UPDATE machine_machine SET config = '{}'")
        config_file.write_text(original)
        stdout, stderr, code = run_python_cwd(
            f"""
import django
django.setup()
from django.db import connection, transaction
from archivebox.machine.models import Machine
from archivebox.config.constants import CONSTANTS
if {readonly!r}:
    connection.close()
    connection.settings_dict["NAME"] = CONSTANTS.DATABASE_FILE.as_uri() + "?mode=ro"
    Machine.current()
else:
    with transaction.atomic():
        Machine.current()
        assert CONSTANTS.CONFIG_FILE.read_text() == {original!r}
        transaction.set_rollback(True)
assert CONSTANTS.CONFIG_FILE.read_text() == {original!r}
assert not any((value or {{}}).get("_SECRET_KEY_DB") for value in Machine.objects.values_list("config", flat=True))
""",
            cwd=initialized_archive,
        )
        assert code == 0, stderr
        if readonly:
            assert "keeping file (OperationalError)" in " ".join(stderr.split())
        assert config_file.read_text() == original


@pytest.mark.parametrize("failure", ["corrupt-db", "missing-table", "unwritable-file", "env-override"])
def test_secret_bootstrap_guards_use_real_files_and_environment(initialized_archive, failure):
    stdout, stderr, code = run_python_cwd(
        f"""
import os
import sqlite3
from pathlib import Path
from archivebox.config.common import get_config
from archivebox.config.collection import _write_file_if_changed
from archivebox.misc.db import load_db_secret
config = get_config(include_machine=False)
config_path = Path("ArchiveBox.conf")
original = config_path.read_bytes()
if {failure!r} == "unwritable-file":
    Path.cwd().chmod(0o500)
    try:
        assert not _write_file_if_changed("replacement")
        assert config_path.read_bytes() == original
    finally:
        Path.cwd().chmod(0o700)
else:
    if {failure!r} == "env-override":
        os.environ["SECRET_KEY"] = "explicit-process-secret"
    else:
        config.DATABASE_NAME = str(Path("unavailable.sqlite3").absolute())
        if {failure!r} == "corrupt-db":
            Path(config.DATABASE_NAME).write_bytes(b"not a SQLite database")
        else:
            sqlite3.connect(config.DATABASE_NAME).close()
    assert load_db_secret(config) is None
    assert config_path.read_bytes() == original
""",
        cwd=initialized_archive,
    )
    assert code == 0, stderr
    if failure in ("corrupt-db", "unwritable-file"):
        assert "Unable to" in stderr


def test_config_read_get_and_search_cover_core_plugin_alias_and_path_options(initialized_archive):
    """Exercise every read-only CLI branch against one unchanged collection."""
    result = run_archivebox_cmd(["config"], cwd=initialized_archive)
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert len(output) > 100
    assert "TIMEOUT" in output or "OUTPUT_PERMISSIONS" in output
    assert "DATA_DIR" in output
    assert output.count("\nDATA_DIR =") == 1
    assert str(initialized_archive) in output.replace("\n", "")
    assert "PERSONAS_DIR" in output
    assert output.count("\nPERSONAS_DIR =") == 1
    assert "SNAP_DIR" not in output
    assert "CRAWL_DIR" not in output

    data_dir = run_archivebox_cmd(["config", "--get", "DATA_DIR"], cwd=initialized_archive)
    assert isinstance(data_dir.stdout, str) and isinstance(data_dir.stderr, str)
    snap_dir = run_archivebox_cmd(["config", "--get", "SNAP_DIR"], cwd=initialized_archive)
    assert isinstance(snap_dir.stdout, str) and isinstance(snap_dir.stderr, str)

    assert data_dir.returncode == 0, data_dir.stderr
    assert "DATA_DIR" in data_dir.stdout
    assert str(initialized_archive) in data_dir.stdout.replace("\n", "")
    assert snap_dir.returncode != 0
    assert "SNAP_DIR =" not in snap_dir.stdout

    result = run_archivebox_cmd(
        ["config", "--get", "TIMEOUT"],
    )
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)

    assert result.returncode == 0
    assert "TIMEOUT" in result.stdout

    for query, expected in (("TIMEOUT", "TIMEOUT"), ("wget", "WGET_BINARY"), ("URL_BLACK", "URL_DENYLIST")):
        result = run_archivebox_cmd(["config", "--search", query])
        assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
        assert result.returncode == 0, result.stderr
        assert expected in result.stdout, query


def test_config_rejects_readonly_runtime_unknown_and_malformed_keys(initialized_archive):
    """Each rejected input must fail through its own CLI validation branch."""
    data_dir = run_archivebox_cmd(
        ["config", "--set", f"DATA_DIR={initialized_archive / 'other'}"],
        cwd=initialized_archive,
    )
    assert isinstance(data_dir.stdout, str) and isinstance(data_dir.stderr, str)
    crawl_dir = run_archivebox_cmd(
        ["config", "--set", f"CRAWL_DIR={initialized_archive / 'crawl'}"],
        cwd=initialized_archive,
    )
    assert isinstance(crawl_dir.stdout, str) and isinstance(crawl_dir.stderr, str)

    assert data_dir.returncode != 0
    assert crawl_dir.returncode != 0
    content = (initialized_archive / "ArchiveBox.conf").read_text()
    assert "DATA_DIR" not in content
    assert "CRAWL_DIR" not in content

    result = run_archivebox_cmd(
        ["config", "--set", "TOTALLY_INVALID_KEY_XYZ=value"],
    )
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)

    assert result.returncode != 0

    result = run_archivebox_cmd(
        ["config", "--set", "TIMEOUT"],
    )
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)

    assert result.returncode != 0


def test_config_set_update_get_preserves_other_keys(initialized_archive):
    """Exercise each write path against one real config, checking each transition."""
    result = run_archivebox_cmd(["config", "--set", "TIMEOUT=120"])
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
    assert result.returncode == 0, result.stderr
    assert "TIMEOUT=120" in result.stdout
    config_file = initialized_archive / "ArchiveBox.conf"
    assert config_file.is_file()
    content = config_file.read_text()
    assert "TIMEOUT" in content and "120" in content
    assert "[" in content or "=" in content
    assert read_ini_config(config_file)["TIMEOUT"] == "120"

    result = run_archivebox_cmd(["config", "--set", "YTDLP_TIMEOUT=200"])
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
    assert result.returncode == 0, result.stderr
    content = config_file.read_text()
    assert "TIMEOUT" in content
    assert "YTDLP_TIMEOUT" in content
    assert read_ini_config(config_file)["TIMEOUT"] == "120"
    assert read_ini_config(config_file)["YTDLP_TIMEOUT"] == "200"

    updated = run_archivebox_cmd(["config", "--set", "TIMEOUT=654"])
    assert isinstance(updated.stdout, str) and isinstance(updated.stderr, str)
    assert updated.returncode == 0, updated.stderr
    assert "TIMEOUT=654" in updated.stdout
    result = run_archivebox_cmd(["config", "--get", "TIMEOUT"])
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
    assert result.returncode == 0, result.stderr
    assert "654" in result.stdout
    assert read_ini_config(config_file)["TIMEOUT"] == "654"
    assert read_ini_config(config_file)["YTDLP_TIMEOUT"] == "200"


def test_config_set_multiple_values_in_fresh_sections(initialized_archive):
    """Keep first writes into new sections distinct from updating existing keys."""
    result = run_archivebox_cmd(["config", "--set", "TIMEOUT=111", "YTDLP_TIMEOUT=222"])
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
    assert result.returncode == 0, result.stderr
    config_file = initialized_archive / "ArchiveBox.conf"
    content = config_file.read_text()
    assert "111" in content
    assert "222" in content
    assert read_ini_config(config_file)["TIMEOUT"] == "111"
    assert read_ini_config(config_file)["YTDLP_TIMEOUT"] == "222"


def test_config_ignores_legacy_unknown_keys(tmp_path, initialized_archive):
    """Old ArchiveBox.conf keys should not prevent startup during upgrades."""
    (tmp_path / "ArchiveBox.conf").write_text(
        """
[ARCHIVING_CONFIG]
MAX_MEDIA_SIZE = "750m"

[SEARCH_BACKEND_CONFIG]
SEARCH_BACKEND_HOST_NAME = "sonic"
SEARCH_BACKEND_PASSWORD = "SecretPassword"
""",
    )

    result = run_archivebox_cmd(
        ["version", "--binaries=curl"],
    )
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)

    assert result.returncode == 0, result.stderr
    assert "Extra inputs are not permitted" not in result.stderr


def test_inaccessible_config_file_is_ignored(tmp_path):
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    config_file = private_dir / "ArchiveBox.conf"
    config_file.write_text("[SERVER_CONFIG]\nDEBUG = True\n")
    private_dir.chmod(0o000)
    try:
        assert read_ini_config(config_file) == {}
    finally:
        private_dir.chmod(0o700)


def test_config_file_preserves_literal_percent_templates(tmp_path):
    config_file = tmp_path / "ArchiveBox.conf"
    config_file.write_text("[ARCHIVING_CONFIG]\nYTDLP_OUTPUT_TEMPLATE = %(title)s.%(ext)s\n")

    assert read_ini_config(config_file)["YTDLP_OUTPUT_TEMPLATE"] == "%(title)s.%(ext)s"


def test_ytdlp_args_env_var_aliases(initialized_archive, tmp_path):
    """Legacy YOUTUBEDL_ARGS / YTDLP_EXTRA_ARGS env vars resolve to canonical YTDLP_ARGS_EXTRA.

    Regression test for https://github.com/ArchiveBox/ArchiveBox/issues/1613.
    The alias lives in the ytdlp plugin config schema (abx-plugins x-aliases);
    if the pinned package ships a schema without the alias, the env var is silently ignored.
    """
    env = {"YOUTUBEDL_ARGS": '["--restrict-filenames"]'}

    result = run_archivebox_cmd(["config", "--get", "YOUTUBEDL_ARGS"], cwd=initialized_archive, env=env)
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
    assert result.returncode == 0, result.stderr
    assert "YTDLP_ARGS_EXTRA =" in result.stdout, result.stdout
    assert "--restrict-filenames" in result.stdout, result.stdout

    result = run_archivebox_cmd(
        ["config", "--get", "YTDLP_EXTRA_ARGS"],
        cwd=initialized_archive,
        env={"YTDLP_EXTRA_ARGS": '["--limit-rate=10M"]'},
    )
    assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
    assert result.returncode == 0, result.stderr
    assert "YTDLP_ARGS_EXTRA =" in result.stdout, result.stdout
    assert "--limit-rate=10M" in result.stdout, result.stdout


class TestConfigCLI:
    """Test the CLI interface for config command."""

    def test_cli_help(self, tmp_path, initialized_archive):
        """Test that --help works for config command."""

        result = run_archivebox_cmd(
            ["config", "--help"],
        )
        assert isinstance(result.stdout, str) and isinstance(result.stderr, str)

        assert result.returncode == 0
        assert "--get" in result.stdout
        assert "--set" in result.stdout
