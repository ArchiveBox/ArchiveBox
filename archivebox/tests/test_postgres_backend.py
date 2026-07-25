#!/usr/bin/env python3
"""
End-to-end tests for the PostgreSQL database backend (DATABASE_ENGINE=postgres).

Spins up a real throwaway PostgreSQL cluster (initdb + pg_ctl) for the module,
then exercises real archivebox CLI flows against it: init, status, re-init,
add --index-only, list, remove, and a full schema-vs-models parity check.

Requires PostgreSQL server binaries (initdb/pg_ctl) to be installed.
"""

import os
import shlex
import shutil
import socket
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

from .conftest import cli_env, run_archivebox_cmd, run_queued_crawls


def _find_pg_bindir() -> Path:
    """Locate PostgreSQL server binaries (initdb) on this machine."""
    initdb_on_path = shutil.which("initdb")
    if initdb_on_path:
        return Path(initdb_on_path).resolve().parent
    candidates = []
    for base in (Path("/usr/lib/postgresql"), Path("/opt/homebrew/opt"), Path("/usr/local/opt"), Path("/opt/homebrew/Cellar/postgresql")):
        if base.is_dir():
            for sub in sorted(base.iterdir(), reverse=True):
                initdb = sub / "bin" / "initdb"
                if initdb.is_file():
                    candidates.append(initdb.parent)
    assert candidates, "PostgreSQL server binaries (initdb) are required for test_postgres_backend tests"
    return candidates[0]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


PG_TEST_USER = "abxtest"


@pytest.fixture(scope="module")
def pg_server():
    """A real throwaway PostgreSQL server for the whole test module."""
    bindir = _find_pg_bindir()
    workdir = Path(tempfile.mkdtemp(prefix="abx-pg-test-"))
    datadir = workdir / "data"
    logfile = workdir / "server.log"
    port = _free_port()

    # postgres refuses to run as root; when the suite runs as root (e.g. in a
    # dev container), run the server as the system postgres user instead.
    run_as_postgres_user = os.geteuid() == 0
    if run_as_postgres_user:
        workdir.chmod(0o755)
        shutil.chown(workdir, user="postgres")

    def pg_cmd(args: list[str]) -> subprocess.CompletedProcess:
        if run_as_postgres_user:
            full = ["su", "postgres", "-s", "/bin/sh", "-c", shlex.join(args)]
        else:
            full = args
        return subprocess.run(full, capture_output=True, text=True, check=False, timeout=120)

    result = pg_cmd([str(bindir / "initdb"), "-D", str(datadir), "-E", "UTF8", "-A", "trust", "-U", PG_TEST_USER])
    assert result.returncode == 0, f"initdb failed: {result.stderr}"

    server_opts = f"-p {port} -k {workdir} -c listen_addresses=127.0.0.1 -c fsync=off -c synchronous_commit=off"
    result = pg_cmd([str(bindir / "pg_ctl"), "-D", str(datadir), "-l", str(logfile), "-o", server_opts, "-w", "start"])
    assert result.returncode == 0, f"pg_ctl start failed: {result.stderr}\n{logfile.read_text() if logfile.exists() else ''}"

    try:
        yield {"host": "127.0.0.1", "port": port, "user": PG_TEST_USER}
    finally:
        pg_cmd([str(bindir / "pg_ctl"), "-D", str(datadir), "-m", "immediate", "stop"])
        shutil.rmtree(workdir, ignore_errors=True)


def pg_cli_env(pg_server: dict, dbname: str, **extra) -> dict:
    env = cli_env(**extra)
    env.update(
        {
            "ARCHIVEBOX_DATABASE_ENGINE": "postgres",
            "ARCHIVEBOX_DATABASE_HOST": pg_server["host"],
            "ARCHIVEBOX_DATABASE_PORT": str(pg_server["port"]),
            "ARCHIVEBOX_DATABASE_USER": pg_server["user"],
            "ARCHIVEBOX_DATABASE_NAME": dbname,
        },
    )
    return env


def unique_dbname() -> str:
    return f"abx_test_{uuid.uuid4().hex[:12]}"


def pg_query(pg_server: dict, dbname: str, query: str) -> list[tuple]:
    import psycopg

    with psycopg.connect(host=pg_server["host"], port=pg_server["port"], user=pg_server["user"], dbname=dbname) as conn:
        return conn.execute(query).fetchall()


def test_init_creates_postgres_schema(pg_server, tmp_path):
    """Fresh init against postgres should create the database + full schema, and no sqlite file."""
    dbname = unique_dbname()
    env = pg_cli_env(pg_server, dbname)

    result = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, env=env, timeout=300)
    assert result.returncode == 0, f"Init failed: {result.stderr}\n{result.stdout}"

    assert not (tmp_path / "index.sqlite3").exists(), "sqlite file should not be created when using postgres"
    assert (tmp_path / "archive").is_dir(), "Archive dir not created"

    (applied_migrations,) = pg_query(pg_server, dbname, "SELECT COUNT(*) FROM django_migrations")[0]
    assert applied_migrations > 50, f"Expected all migrations applied, got {applied_migrations}"

    for table in ("core_snapshot", "core_archiveresult", "core_tag", "crawls_crawl", "machine_machine", "api_apitoken", "personas_persona"):
        (regclass,) = pg_query(pg_server, dbname, f"SELECT to_regclass('{table}')")[0]
        assert regclass == table, f"Table {table} missing from postgres schema"


def test_postgres_schema_matches_models(pg_server, tmp_path):
    """Every model column must exist in postgres and vice versa (no state/schema drift)."""
    dbname = unique_dbname()
    env = pg_cli_env(pg_server, dbname)

    result = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, env=env, timeout=300)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    parity_script = (
        "from django.apps import apps\n"
        "from django.db import connection\n"
        "problems = []\n"
        "with connection.cursor() as cursor:\n"
        "    tables = set(connection.introspection.table_names(cursor))\n"
        "    for model in apps.get_models(include_auto_created=True):\n"
        "        meta = model._meta\n"
        "        if not meta.managed or meta.proxy:\n"
        "            continue\n"
        "        if meta.db_table not in tables:\n"
        "            problems.append(f'missing table {meta.db_table}')\n"
        "            continue\n"
        "        db_cols = {col.name for col in connection.introspection.get_table_description(cursor, meta.db_table)}\n"
        "        model_cols = {field.column for field in meta.local_concrete_fields}\n"
        "        for col in sorted(model_cols - db_cols):\n"
        "            problems.append(f'{meta.db_table}: missing column {col}')\n"
        "        for col in sorted(db_cols - model_cols):\n"
        "            problems.append(f'{meta.db_table}: extra column {col}')\n"
        "print('SCHEMA_PROBLEMS=' + repr(sorted(problems)))\n"
    )
    result = run_archivebox_cmd(["manage", "shell", "-c", parity_script], cwd=tmp_path, env=env, timeout=120)
    assert result.returncode == 0, f"manage shell failed: {result.stderr}"
    assert "SCHEMA_PROBLEMS=[]" in result.stdout, f"Postgres schema diverges from models:\n{result.stdout}\n{result.stderr}"

    result = run_archivebox_cmd(["manage", "makemigrations", "--check", "--dry-run"], cwd=tmp_path, env=env, timeout=120)
    assert result.returncode == 0, f"Model state does not match migrations: {result.stdout}\n{result.stderr}"


def test_status_and_reinit_on_postgres(pg_server, tmp_path):
    """status works against postgres, and a second init takes the 'verify existing' path."""
    dbname = unique_dbname()
    env = pg_cli_env(pg_server, dbname)

    result = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, env=env, timeout=300)
    assert result.returncode == 0, f"Init failed: {result.stderr}"
    assert "Initializing a new ArchiveBox" in result.stdout

    result = run_archivebox_cmd(["status"], cwd=tmp_path, env=env, timeout=120)
    assert result.returncode == 0, f"Status failed: {result.stderr}"
    assert f"postgresql://{PG_TEST_USER}@" in result.stdout, f"status should show the postgres DSN:\n{result.stdout}"

    result = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, env=env, timeout=300)
    assert result.returncode == 0, f"Re-init failed: {result.stderr}"
    assert "Verifying and updating existing ArchiveBox collection" in result.stdout


def test_add_list_remove_on_postgres(pg_server, tmp_path):
    """Real add/list/remove CLI flows store and retrieve rows from postgres."""
    dbname = unique_dbname()
    env = pg_cli_env(pg_server, dbname, disable_extractors=True)
    test_url = "https://example.com/abx-postgres-test"

    result = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, env=env, timeout=300)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_cmd(["add", "--index-only", test_url], cwd=tmp_path, env=env, timeout=300)
    assert result.returncode == 0, f"Add failed: {result.stderr}\n{result.stdout}"
    run_queued_crawls(tmp_path, env)

    (snapshot_count,) = pg_query(pg_server, dbname, "SELECT COUNT(*) FROM core_snapshot")[0]
    assert snapshot_count >= 1, "Snapshot row not written to postgres"
    (crawl_count,) = pg_query(pg_server, dbname, "SELECT COUNT(*) FROM crawls_crawl")[0]
    assert crawl_count >= 1, "Crawl row not written to postgres"

    result = run_archivebox_cmd(["list"], cwd=tmp_path, env=env, timeout=120)
    assert result.returncode == 0, f"List failed: {result.stderr}"
    assert "example.com/abx-postgres-test" in result.stdout, f"Added URL missing from list output:\n{result.stdout}"

    result = run_archivebox_cmd(["search", "abx-postgres-test"], cwd=tmp_path, env=env, timeout=120)
    assert result.returncode == 0, f"Search failed: {result.stderr}"
    assert "example.com/abx-postgres-test" in result.stdout, f"Added URL missing from search output:\n{result.stdout}"

    result = run_archivebox_cmd(
        ["remove", "--yes", "--delete", "--filter-type=exact", test_url],
        cwd=tmp_path,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, f"Remove failed: {result.stderr}\n{result.stdout}"
    (snapshot_count,) = pg_query(pg_server, dbname, f"SELECT COUNT(*) FROM core_snapshot WHERE url = '{test_url}'")[0]
    assert snapshot_count == 0, "Snapshot row should be deleted from postgres"


def test_sqlite_remains_the_default(tmp_path):
    """Without DATABASE_ENGINE config, init keeps using the sqlite file backend."""
    result = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, env=cli_env(), timeout=300)
    assert result.returncode == 0, f"Init failed: {result.stderr}"
    assert (tmp_path / "index.sqlite3").exists(), "sqlite file should be created by default"
