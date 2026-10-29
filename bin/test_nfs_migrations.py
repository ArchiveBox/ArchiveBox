"""Real NFS filesystem migration probe; run with uv run python on a Linux client.

Requires two NEW directories: --local-root on a local filesystem and
--archive-root on a mounted NFS export. Never point these at a real collection.
No server/export provisioning is performed by this script.
"""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import random
import select
import signal
import shutil
import sqlite3
import stat
import struct
import subprocess
import time


def manifest(root):
    entries = {}
    for path in root.rglob("*"):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            entries[relative] = ["symlink", str(path.readlink())]
        elif path.is_file():
            with path.open("rb") as contents:
                entries[relative] = ["file", hashlib.file_digest(contents, "sha256").hexdigest(), stat.S_IMODE(path.stat().st_mode)]
        elif path.is_dir():
            entries[relative] = ["dir"]
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", required=True, type=Path)
    parser.add_argument("--archive-root", required=True, type=Path)
    parser.add_argument("--seed", default=1932, type=int)
    args = parser.parse_args()
    assert os.geteuid() != 0, "Run as an unprivileged user so permission failures are exercised"
    args.local_root.mkdir()
    args.archive_root.mkdir()
    local_fs = subprocess.check_output(["stat", "-f", "-c", "%T", str(args.local_root)], text=True).strip()
    remote_fs = subprocess.check_output(["stat", "-f", "-c", "%T", str(args.archive_root)], text=True).strip()
    assert local_fs not in {"nfs", "nfs4"} and remote_fs in {"nfs", "nfs4"}, (local_fs, remote_fs)
    collection = args.local_root / "collection"
    collection.mkdir()
    env = os.environ.copy()
    for key in ("ARCHIVE_DIR", "USERS_DIR", "CRAWL_DIR", "SNAP_DIR"):
        env.pop(key, None)
    env.update(DATA_DIR=str(collection), PLUGINS="__archivebox_test_no_plugins__", PYTHONUNBUFFERED="1")
    commands = []

    def command(arguments, expected=0, interrupt_dir=None, large_size=0, interrupt_prefix=""):
        log = args.local_root / f"command-{len(commands):02d}.log"
        started = time.monotonic()
        watch_fd = None
        if interrupt_dir:
            libc = ctypes.CDLL(None, use_errno=True)
            watch_fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
            assert watch_fd >= 0
            assert libc.inotify_add_watch(watch_fd, os.fsencode(interrupt_dir), 0x100) >= 0  # IN_CREATE
        with log.open("w") as output:
            process = subprocess.Popen(["archivebox", *arguments], cwd=collection, env=env, stdout=output, stderr=output)
            interrupted = None
            try:
                while process.poll() is None:
                    if watch_fd is not None and interrupted is None and select.select([watch_fd], [], [], 0)[0]:
                        events = os.read(watch_fd, 65536)
                        names = []
                        while events:
                            _watch, _mask, _cookie, size = struct.unpack("iIII", events[:16])
                            names.append(os.fsdecode(events[16 : 16 + size].split(b"\0", 1)[0]))
                            events = events[16 + size :]
                        for name in names:
                            if not name.startswith(interrupt_prefix):
                                continue
                            candidate = interrupt_dir / name
                            if candidate.is_file() and candidate.stat().st_size < large_size:
                                process.send_signal(signal.SIGSTOP)
                                interrupted = {
                                    "path": str(candidate),
                                    "partial_size": candidate.stat().st_size,
                                    "complete_size": large_size,
                                }
                                process.send_signal(signal.SIGKILL)
                                break
                    assert time.monotonic() - started < 300, f"Command timed out: {log}"
                    time.sleep(0.005)
                process.wait(timeout=10)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                if watch_fd is not None:
                    os.close(watch_fd)
        commands.append(
            {
                "args": arguments,
                "exit_code": process.returncode,
                "seconds": round(time.monotonic() - started, 3),
                "interruption": interrupted,
            },
        )
        (args.local_root / "commands.json").write_text(json.dumps(commands, indent=2))
        assert process.returncode == expected, log.read_text()[-12000:]
        assert not interrupt_dir or interrupted, "Did not interrupt an actual partial file copy"
        print(json.dumps(commands[-1]), flush=True)

    command(["init", "--quick"])
    for entry in (collection / "archive").iterdir():
        shutil.move(str(entry), str(args.archive_root / entry.name))
    (collection / "archive").rmdir()
    (collection / "archive").symlink_to(args.archive_root, target_is_directory=True)
    plan = args.local_root / "snapshots.json"
    seed_code = f"""
import json
from pathlib import Path
from archivebox.core.models import Snapshot, ArchiveResult
from archivebox.crawls.models import Crawl
crawl = Crawl.objects.create(urls='https://example.com/nfs/{args.seed}', status='sealed', retry_at=None)
rows = []
for i in range(24):
    snapshot = Snapshot.objects.create(crawl=crawl, url=f'https://example.com/nfs/{args.seed}/{{i}}', status='sealed', retry_at=None, fs_version='0.8.0')
    Snapshot.objects.filter(pk=snapshot.pk).update(fs_version='0.8.0')
    ArchiveResult.objects.create(snapshot=snapshot, plugin='wget', hook_name='on_Snapshot__wget', status='succeeded', output_str='wget/index.html')
    rows.append(dict(id=str(snapshot.pk).replace('-', ''), timestamp=snapshot.timestamp, old=str(snapshot.get_storage_path_for_version('0.8.0')), new=str(snapshot.get_storage_path_for_version(snapshot._fs_current_version())), version=snapshot._fs_current_version()))
Path({str(plan)!r}).write_text(json.dumps(rows))
"""
    command(["manage", "shell", "-c", seed_code])
    rows = json.loads(plan.read_text())
    rng = random.Random(args.seed)
    expected = {}
    for i, row in enumerate(rows):
        old, new = Path(row["old"]), Path(row["new"])
        (old / "payload" / "empty").mkdir(parents=True)
        (old / "wget").mkdir()
        (old / "wget/index.html").write_text(f"<html>seed {args.seed} capture {i} 雪</html>")
        for j in range(16):
            path = old / "payload" / f"{j:02d} quoted ' 雪.bin"
            path.write_bytes(rng.randbytes(rng.choice([0, 31, 4096, 65536, 131072])))
            path.chmod(rng.choice([0o444, 0o640, 0o644]))
        (old / "payload" / "relative-link").symlink_to("../wget/index.html")
        (old / "payload" / "broken-link").symlink_to("missing-file")
        if i % 3 == 0:
            new.mkdir(parents=True, exist_ok=True)
            (new / "destination-only.bin").write_bytes(b"pre-existing destination evidence")
        expected[row["id"]] = manifest(old)
    # Force a real NFS copy (rather than a directory rename) and interrupt it
    # while the destination or staging file is observably incomplete.
    crash = rows[0]
    large_size = 64 * 1024 * 1024
    old_large = Path(crash["old"]) / "large"
    new_large = Path(crash["new"]) / "large"
    old_large.mkdir()
    new_large.mkdir()
    with (old_large / "large.bin").open("wb") as output:
        for _ in range(64):
            output.write(rng.randbytes(1024 * 1024))
    expected[crash["id"]] = manifest(Path(crash["old"]))
    (args.local_root / "expected.json").write_text(json.dumps(expected))
    selected = ["update", "--migrate-only", "--filter-type", "timestamp"]
    command(
        [*selected, crash["timestamp"]],
        expected=-signal.SIGKILL,
        interrupt_dir=Path(crash["new"]).parent,
        large_size=large_size,
        interrupt_prefix=f".{crash['id']}.migration-{hashlib.sha256(os.fsencode(new_large / 'large.bin')).hexdigest()[:16]}-",
    )
    assert manifest(Path(crash["old"])) == expected[crash["id"]]
    assert not (new_large / "large.bin").exists(), "An incomplete copy must not be published as captured output"
    with sqlite3.connect(collection / "index.sqlite3") as db:
        assert db.execute("SELECT fs_version FROM core_snapshot WHERE id=?", (crash["id"],)).fetchone()[0] == "0.8.0"
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    command([*selected, crash["timestamp"]])

    conflict = rows[-1]
    source = Path(conflict["old"]) / "payload" / "conflict.bin"
    destination = Path(conflict["new"]) / "payload" / "conflict.bin"
    source.write_bytes(b"source evidence")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"different destination evidence")
    expected[conflict["id"]] = manifest(Path(conflict["old"]))
    for _ in range(2):
        command([*selected, conflict["timestamp"]], expected=1)
        assert source.read_bytes() == b"source evidence"
        assert destination.read_bytes() == b"different destination evidence"
        with sqlite3.connect(collection / "index.sqlite3") as db:
            assert db.execute("SELECT fs_version FROM core_snapshot WHERE id=?", (conflict["id"],)).fetchone()[0] == "0.8.0"
    # Resolve only this deliberately constructed collision, retaining both files.
    destination.rename(destination.with_name("retained-conflict.bin"))

    protected = rows[1]
    old = Path(protected["old"])
    Path(protected["new"]).mkdir(parents=True, exist_ok=True)
    (old / "payload").chmod(0o555)
    command([*selected, protected["timestamp"]], expected=1)
    for relative, entry in expected[protected["id"]].items():
        # Cleanup may remove some already-verified entries before permissions
        # reject it, but every source byte must exist at one of the two paths.
        assert manifest(old).get(relative) == entry or manifest(Path(protected["new"])).get(relative) == entry
    (old / "payload").chmod(0o755)
    (Path(protected["new"]) / "payload").chmod(0o755)
    (args.local_root / "expected.json").write_text(json.dumps(expected))

    for _ in range(2):
        command(["update", "--rescan", "--migrate-only"])
        for i, row in enumerate(rows):
            assert not Path(row["old"]).exists(), row
            actual = manifest(Path(row["new"]))
            for relative, entry in expected[row["id"]].items():
                assert actual.get(relative) == entry, (row["id"], relative, actual.get(relative), entry)
            if i % 3 == 0:
                assert (Path(row["new"]) / "destination-only.bin").read_bytes() == b"pre-existing destination evidence"
        with sqlite3.connect(collection / "index.sqlite3") as db:
            assert db.execute("SELECT COUNT(*) FROM core_snapshot WHERE fs_version=?", (rows[0]["version"],)).fetchone()[0] == 24
            assert db.execute("SELECT COUNT(*) FROM core_archiveresult").fetchone()[0] == 24
            assert db.execute("SELECT COUNT(*) FROM core_archiveresult WHERE output_size>0 AND output_files!='{}'").fetchone()[0] == 24
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    command(["check"])
    report = {
        "seed": args.seed,
        "snapshots": len(rows),
        "original_entries": sum(map(len, expected.values())),
        "local_filesystem": local_fs,
        "archive_filesystem": remote_fs,
        "commands": commands,
        "passed": True,
    }
    (args.local_root / "result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
