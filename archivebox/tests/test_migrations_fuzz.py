# ci-workers: 1
"""Seeded legacy DB fuzzing through real CLI upgrades, interruption, and reruns.

Run at discussion #1932's scale with ABX_FUZZ_SNAPSHOTS=49000
ABX_FUZZ_RESULTS=349000 uv run pytest -s archivebox/tests/test_migrations_fuzz.py.
Generated collections, logs, and independent expected-row oracles live in tmp_path.
"""

import hashlib
import json
import os
import random
import signal
import sqlite3
import time
from uuid import UUID

import psutil
import pytest

from .conftest import cli_env, run_archivebox_cmd
from .migrations_helpers import SCHEMA_0_7, create_data_dir_structure, seed_0_7_data, verify_preserved_rows


def _digest_rows(db, query):
    digest = hashlib.sha256()
    for row in db.execute(query):
        digest.update(json.dumps(row, ensure_ascii=True).encode() + b"\n")
    return digest.hexdigest()


def _seed_collection(root, seed, snapshots, results, journal):
    collection = root / "collection"
    create_data_dir_structure(collection)
    db_path = collection / "index.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.executescript(SCHEMA_0_7)
    security = seed_0_7_data(db_path)["preserved_rows"]
    rng = random.Random(seed)
    snapshot_ids = []
    statuses = {
        "success": "succeeded",
        "succeded": "succeeded",
        **{s: s for s in ("succeeded", "failed", "skipped", "queued", "started", "backoff", "noresults")},
    }
    with sqlite3.connect(db_path) as db, (root / "expected-results.jsonl").open("w") as expected:
        db.execute(f"PRAGMA journal_mode={journal}")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("DELETE FROM core_snapshot_tags")
        db.execute("DELETE FROM core_archiveresult")
        db.execute("DELETE FROM core_snapshot")
        for i in range(257):
            db.execute("INSERT INTO core_tag(name,slug) VALUES (?,?)", (f"tag-{i}-雪", f"tag-{i}"))
        tag_ids = [row[0] for row in db.execute("SELECT id FROM core_tag")]
        for i in range(snapshots):
            snapshot_id = UUID(int=rng.getrandbits(128), version=4).hex
            snapshot_ids.append(snapshot_id)
            date = f"2023-05-{rng.randrange(1, 29):02d} 12:34:56.123456"
            title = rng.choice([None, "", "雪 🗃 quoted ' \" & <html>", "long " * 100])
            db.execute(
                "INSERT INTO core_snapshot VALUES (?,?,?,?,?,?)",
                (snapshot_id, f"https://example.com/{seed}/{i}?q=%E9%9B%AA", str(1600000000 + i), title, date, rng.choice([None, date])),
            )
            for tag_id in rng.sample(tag_ids, rng.randrange(5)):
                db.execute("INSERT INTO core_snapshot_tags(snapshot_id,tag_id) VALUES (?,?)", (snapshot_id, tag_id))
        for i in range(results):
            # Leave some snapshots empty; concentrate some histories in hot rows.
            snapshot_id = snapshot_ids[rng.randrange(max(1, snapshots // (10 if i % 3 == 0 else 1) - 1))]
            plugin = rng.choice(["wget", "title", "singlefile", "screenshot", "readability", "custom_plugin"])
            raw_status = rng.choice(list(statuses))
            status = statuses[raw_status]
            command = [plugin, "--output", f"path with spaces/雪/{i}", str(rng.randrange(100000))]
            cmd = rng.choice([None, "", json.dumps(command), plugin + " --version"])
            argv = [] if not cmd else command if cmd.startswith("[") else [plugin, "--version"]
            version = rng.choice([None, "", "1.0.0", "2.1+legacy"]) if argv else None
            pwd = rng.choice([None, "", "/data/archive/old path/雪"])
            output = f"result/{i:09d}/" + rng.choice(["", "雪", "x" * 4096, "error: 'quoted'\nsecond line"])
            start = f"2023-06-{rng.randrange(1, 29):02d} 01:02:03.123456"
            end = rng.choice([None, f"2023-06-28 02:03:04.{rng.randrange(1000000):06d}"])
            result_uuid = UUID(int=rng.getrandbits(128), version=4).hex
            if i % 101 == 0:
                result_uuid = "invalid-uuid"
            elif i % 97 == 0:
                result_uuid = "12345678123456781234567812345678"
            db.execute(
                "INSERT INTO core_archiveresult(uuid,snapshot_id,extractor,cmd,pwd,cmd_version,output,start_ts,end_ts,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (result_uuid, snapshot_id, plugin, cmd, pwd, version, output, start, end, raw_status),
            )
            preserved_uuid = result_uuid if i % 101 and i % 97 else None
            expected.write(
                json.dumps([snapshot_id, plugin, status, output, argv, pwd or "", version or "", start, end or start, preserved_uuid])
                + "\n",
            )
        snapshot_digest = _digest_rows(
            db,
            "SELECT id,url,timestamp,title,added,COALESCE(updated,added),updated FROM core_snapshot ORDER BY id",
        )
        tag_digest = _digest_rows(db, "SELECT id,name FROM core_tag ORDER BY id")
        join_digest = _digest_rows(db, "SELECT snapshot_id,tag_id FROM core_snapshot_tags ORDER BY snapshot_id,tag_id")
    return collection, security, (snapshot_digest, tag_digest, join_digest)


def _run(collection, args, journal, *, interrupt=None, error=None):
    """Observe the actual CLI process; never inject handlers into migration code."""
    log = collection.parent / ("-".join(args).replace("/", "_") + ("-killed" if interrupt else "-rejected" if error else "") + ".log")
    started = time.monotonic()
    peak_rss = 0
    killed = False
    with log.open("w") as output, log.open() as progress:
        process = run_archivebox_cmd(
            args,
            cwd=collection,
            wait=False,
            stdout=output,
            stderr=output,
            env=cli_env(
                disable_extractors=True,
                PLUGINS="__archivebox_test_no_plugins__",
                PYTHONUNBUFFERED="1",
                ARCHIVEBOX_SQLITE_JOURNAL_MODE=journal,
            ),
        )
        try:
            while process.poll() is None:
                try:
                    peak_rss = max(peak_rss, psutil.Process(process.pid).memory_info().rss)
                except psutil.NoSuchProcess:
                    pass
                if interrupt and not killed and interrupt in progress.read():
                    process.send_signal(signal.SIGKILL)
                    killed = True
                assert time.monotonic() - started < 900, f"CLI exceeded 900s: {log}"
                time.sleep(0.01)
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGKILL)
                process.wait(timeout=10)
    assert process.returncode == (-signal.SIGKILL if interrupt else 1 if error else 0), log.read_text()[-12000:]
    if error:
        assert error in log.read_text()
    assert not interrupt or killed, f"Never reached interruption point {interrupt}: {log}"
    metrics = {
        "args": args,
        "journal": journal,
        "killed": killed,
        "seconds": round(time.monotonic() - started, 2),
        "sampled_peak_rss_mib": round(peak_rss / 2**20, 1),
    }
    print(json.dumps(metrics), flush=True)
    with (collection.parent / "metrics.jsonl").open("a") as report:
        report.write(json.dumps(metrics) + "\n")


@pytest.mark.parametrize("seed,journal,target", [(1932, "DELETE", "0023"), (722, "WAL", "0027"), (903, "DELETE", "0029")])
@pytest.mark.timeout(1800)
def test_seeded_legacy_upgrade_preserves_every_row(tmp_path, seed, journal, target):
    snapshots = int(os.environ.get("ABX_FUZZ_SNAPSHOTS", "300"))
    results = int(os.environ.get("ABX_FUZZ_RESULTS", "20000"))
    assert snapshots >= 2 and results >= 20000
    collection, security, expected_digests = _seed_collection(tmp_path, seed, snapshots, results, journal)
    db_path = collection / "index.sqlite3"
    print(
        f"seed={seed} snapshots={snapshots} results={results} database_mib={db_path.stat().st_size / 2**20:.1f} collection={collection}",
        flush=True,
    )
    if target != "0023":
        _run(collection, ["manage", "migrate", "core", f"{int(target) - 1:04d}", "--noinput"], journal)
    if target == "0027":
        # This invalid combination is deliberately rejected, not silently
        # normalized. Put it last so the rollback covers a nearly complete copy.
        with sqlite3.connect(db_path) as db:
            last_id, original_cmd, original_version = db.execute(
                "SELECT id,cmd,cmd_version FROM core_archiveresult ORDER BY id DESC LIMIT 1",
            ).fetchone()
            db.execute("UPDATE core_archiveresult SET cmd='[]',cmd_version='unattributable' WHERE id=?", (last_id,))
            invalid_digest = _digest_rows(db, "SELECT * FROM core_archiveresult ORDER BY id")
            process_count = db.execute("SELECT COUNT(*) FROM machine_process").fetchone()[0]
        _run(collection, ["manage", "migrate", "core", target, "--noinput"], journal, error="has cmd_version metadata but no command")
        with sqlite3.connect(db_path) as db:
            assert _digest_rows(db, "SELECT * FROM core_archiveresult ORDER BY id") == invalid_digest
            assert db.execute("SELECT COUNT(*) FROM machine_process").fetchone()[0] == process_count
            assert not db.execute("SELECT 1 FROM django_migrations WHERE app='core' AND name LIKE '0027%'").fetchall()
            # Restore the generated test input, after proving rejection left it intact.
            db.execute("UPDATE core_archiveresult SET cmd=?,cmd_version=? WHERE id=?", (original_cmd, original_version, last_id))
    with sqlite3.connect(db_path) as db:
        original = {
            table: _digest_rows(db, f"SELECT * FROM {table} ORDER BY id")
            for table in ("core_snapshot", "core_tag", "core_snapshot_tags", "core_archiveresult")
        }
        if target != "0023":
            original.update(
                {
                    table: _digest_rows(db, f"SELECT * FROM {table} ORDER BY id")
                    for table in ("machine_process", "machine_binary", "machine_machine")
                },
            )
    progress = "migrated 10000/" if target == "0027" else "copied 10000/"
    _run(collection, ["manage", "migrate", "core", target, "--noinput"], journal, interrupt=progress)
    with sqlite3.connect(db_path) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert not db.execute("SELECT 1 FROM django_migrations WHERE app='core' AND name LIKE ?", (target + "%",)).fetchall()
        for table, digest in original.items():
            assert _digest_rows(db, f"SELECT * FROM {table} ORDER BY id") == digest, f"Interrupted {target} changed {table}"

    for _ in range(2):
        _run(collection, ["init", "--quick"], journal)
        verify_preserved_rows(db_path, security)
        with sqlite3.connect(db_path) as db, (tmp_path / "expected-results.jsonl").open() as expected:
            assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert db.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0] == snapshots
            assert db.execute("SELECT COUNT(*) FROM core_archiveresult").fetchone()[0] == results
            assert db.execute("SELECT COUNT(DISTINCT process_id) FROM core_archiveresult").fetchone()[0] == results
            assert db.execute("SELECT COUNT(*) FROM machine_process").fetchone()[0] == results
            assert (
                _digest_rows(db, "SELECT id,url,timestamp,title,created_at,modified_at,downloaded_at FROM core_snapshot ORDER BY id")
                == expected_digests[0]
            )
            assert _digest_rows(db, "SELECT id,name FROM core_tag ORDER BY id") == expected_digests[1]
            assert _digest_rows(db, "SELECT snapshot_id,tag_id FROM core_snapshot_tags ORDER BY snapshot_id,tag_id") == expected_digests[2]
            rows = db.execute("""
                SELECT ar.snapshot_id,ar.plugin,ar.status,ar.output_str,p.cmd,p.pwd,COALESCE(b.version,''),ar.start_ts,ar.end_ts,ar.id
                FROM core_archiveresult ar JOIN machine_process p ON p.id=ar.process_id
                LEFT JOIN machine_binary b ON b.id=p.binary_id ORDER BY ar.output_str
            """)
            for actual, wanted in zip(rows, expected, strict=True):
                values = list(actual[:-1])
                values[4] = json.loads(values[4])
                wanted_values = json.loads(wanted)
                expected_uuid = wanted_values.pop()
                assert values == wanted_values, f"seed={seed}: {actual[3]} changed"
                assert UUID(actual[-1]).hex == actual[-1]
                if expected_uuid:
                    assert actual[-1] == expected_uuid
    _run(collection, ["check"], journal)
