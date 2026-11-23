"""Deduplicate sealed snapshot files using a collection-local index."""

import ctypes
import errno
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from django.db import close_old_connections
from django.db.models import Q

from archivebox.config.constants import CONSTANTS
from archivebox.core.models import Snapshot
from archivebox.plugins.discovery import get_snapshot_file_inventory


def regular(root, name):
    """Reject absolute paths, traversal and symlinks, including parent symlinks."""
    rel = Path(name)
    if rel.is_absolute() or ".." in rel.parts or any(part.casefold() == ".persona" for part in rel.parts):
        raise ValueError("expected a collection-relative file")
    path = root / rel
    if path.resolve(strict=True) != path or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("expected an ordinary file")
    return path


def clone(source, target):
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.clonefile(os.fsencode(source), os.fsencode(target), 0):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
    elif sys.platform == "linux":
        with source.open("rb") as src, target.open("xb") as dst:
            fcntl.ioctl(dst.fileno(), 0x40049409, src.fileno())  # FICLONE
    else:
        raise OSError(errno.ENOTSUP, "clone unsupported")


def replace(source, dest, unsupported):
    src, dst = source.stat(), dest.stat()
    if os.path.samestat(src, dst):
        return "already shared"
    if (src.st_mode, src.st_uid, src.st_gid) != (dst.st_mode, dst.st_uid, dst.st_gid):
        return "kept"
    pair = (src.st_dev, dst.st_dev)
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix=".dedupe-") as stage:
        tmp = Path(stage) / "file"
        for method in ("hardlink", "clone", "symlink"):
            if (*pair, method) in unsupported:
                continue
            try:
                if method == "hardlink":
                    os.link(source, tmp)
                elif method == "clone":
                    clone(source, tmp)
                    shutil.copystat(dest, tmp)
                else:
                    # Relative to the link's final directory.
                    tmp.symlink_to(os.path.relpath(source, dest.parent))
            except OSError as err:
                tmp.unlink(missing_ok=True)
                if err.errno in (errno.ENOTSUP, errno.ENOSYS, errno.EXDEV, errno.ENOTTY):
                    unsupported.add((*pair, method))
                continue
            os.replace(tmp, dest)
            return method
    return "kept"


def eligible(name):
    path = Path(name)
    return (
        not path.is_absolute()
        and len(path.parts) >= 2
        and not any(part.startswith(".") for part in path.parts)
        and not path.name.startswith("on_Snapshot__")
        and path.parts[0] not in {"hashes", "opentimestamps", "chrome_profile", "archivebox-extensions"}
    )


def inventory(directory):
    regular(directory, "hashes/hashes.json")
    marker = directory / "hashes/hashes.sha256"
    if marker.is_symlink():
        raise ValueError("unexpected inventory marker link")
    verify = marker.exists()
    if verify:
        regular(directory, "hashes/hashes.sha256")
    return get_snapshot_file_inventory(directory, verify=verify) or {}


def verified(root, name, sha, size):
    if not eligible(name):
        raise ValueError("not a retained output path")
    path = regular(root, name)
    with path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size != size or hashlib.file_digest(stream, "sha256").digest() != sha:
            raise ValueError("stale file")
    return path


def scope(row):
    return (row.crawl.created_by_id, row.crawl.persona_id, row.permissions)


def index_snapshot(snapshot_id, snapshot, index, scope, authorized_roots):
    groups = defaultdict(list)
    for name, meta in inventory(snapshot).items():
        sha, size = meta.get("hash"), meta.get("size")
        if (
            eligible(name)
            and not meta.get("is_dir")
            and isinstance(size, int)
            and size > 0
            and isinstance(sha, str)
            and sha != "0" * 64
            and re.fullmatch("[0-9a-f]{64}", sha)
        ):
            groups[bytes.fromhex(sha), size].append(name)
    counts = Counter()
    unsupported = set()
    db = sqlite3.connect(index, timeout=0.5)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS files (
            scope TEXT, hash BLOB, size INTEGER, snapshot BLOB NOT NULL, path TEXT NOT NULL,
            PRIMARY KEY(scope, hash, size)) WITHOUT ROWID""")
        keys = list(groups)
        for offset in range(0, len(keys), 200):
            batch = keys[offset : offset + 200]
            with db:
                db.executemany(
                    "INSERT OR IGNORE INTO files VALUES (?,?,?,?,?)",
                    ((scope, h, n, snapshot_id, groups[h, n][0]) for h, n in batch),
                )
            terms = ",".join("(?,?)" for _ in batch)
            matches = db.execute(
                f"SELECT hash,size,snapshot,path FROM files WHERE scope=? AND (hash,size) IN ({terms})",
                [scope, *(v for pair in batch for v in pair)],
            ).fetchall()
            prior_paths = defaultdict(list)
            for digest, size, sid, name in matches:
                if sid != snapshot_id:
                    prior_paths[sid].append((digest, size, name))
            sources = authorized_roots(prior_paths) if prior_paths else {}
            for sha, size, sid, saved in matches:
                paths = groups[sha, size]
                if sid == snapshot_id and saved == paths[0] and len(paths) == 1:
                    continue

                try:
                    root = snapshot if sid == snapshot_id and saved in paths else sources[sid, saved]
                    source = verified(root, saved, sha, size)
                except (KeyError, OSError, ValueError, RuntimeError):
                    # A historical source can vanish or change scope. Elect a
                    # verified local representative without overwriting another winner.
                    for name in paths:
                        try:
                            source = verified(snapshot, name, sha, size)
                            break
                        except (OSError, ValueError, RuntimeError):
                            continue
                    else:
                        continue
                    with db:
                        won = db.execute(
                            "UPDATE files SET snapshot=?,path=? WHERE scope=? AND hash=? AND size=? AND snapshot=? AND path=?",
                            (snapshot_id, name, scope, sha, size, sid, saved),
                        ).rowcount
                    if not won:
                        continue
                for name in paths:
                    try:
                        if snapshot / name != source:
                            dest = verified(snapshot, name, sha, size)
                            counts[replace(source, dest, unsupported)] += 1
                    except (OSError, ValueError, RuntimeError):
                        counts["kept"] += 1
    finally:
        db.close()
    return counts


def directory(row):
    path = row.output_dir.absolute()
    path.relative_to(CONSTANTS.ARCHIVE_DIR)
    if path not in row.storage_path_candidates() or path.resolve(strict=True) != path:
        raise ValueError("unexpected snapshot directory symlink")
    return path


def deduplicate_sealed(pk):
    try:
        snapshots = Snapshot.objects.filter(status="sealed", retry_at__isnull=True).select_related("crawl__created_by")
        row = snapshots.filter(pk=pk).first()
        if row is None:
            return {}
        if not row.archiveresult_set.filter(plugin="hashes", status="succeeded").exists():
            return {}
        owner, persona, visibility = scope(row)
        scoped = snapshots.filter(crawl__created_by_id=owner, crawl__persona_id=persona, permissions=visibility)

        def authorized_roots(prior_paths):
            sources = {}
            for prior in scoped.filter(pk__in=[uuid.UUID(bytes=k) for k in prior_paths]):
                try:
                    root = directory(prior)
                    retained = inventory(root)
                    for digest, size, name in prior_paths[prior.pk.bytes]:
                        entry = retained.get(name) or {}
                        if entry.get("hash") == digest.hex() and entry.get("size") == size and not entry.get("is_dir"):
                            sources[prior.pk.bytes, name] = root
                except (OSError, ValueError, RuntimeError):
                    continue
            return sources

        return index_snapshot(
            row.pk.bytes,
            directory(row),
            CONSTANTS.DATA_DIR / "hashes.sqlite3",
            json.dumps([str(owner), str(persona) if persona else None, visibility]),
            authorized_roots,
        )
    except Exception:
        logging.getLogger(__name__).exception("File deduplication failed for sealed snapshot %s", pk)
        return {"errors": 1}
    finally:
        close_old_connections()


def snapshot_location(path):
    """Identify the snapshot boundary in a current or timestamp-based collection layout."""
    archive = CONSTANTS.ARCHIVE_DIR
    parts = path.relative_to(archive).parts
    if len(parts) >= 6 and parts[0] == "users" and parts[2] == "snapshots":
        return archive.joinpath(*parts[:6]), Q(pk=uuid.UUID(parts[5]))
    if parts and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", parts[0]):
        return archive / parts[0], Q(timestamp=parts[0])
    raise ValueError("outside a snapshot")


def permitted_shared_file(root, path, target):
    """Allow retained files between sealed snapshots in the same live access scope."""
    try:
        dst, dst_filter = snapshot_location(root)
        src, src_filter = snapshot_location(target)
        if not target.is_file():
            return False
        rows = Snapshot.objects.filter(dst_filter | src_filter, status="sealed", retry_at__isnull=True).select_related("crawl__created_by")
        owners = {directory(row): scope(row) for row in rows}
        if dst not in owners or owners[dst] != owners.get(src):
            return False
        # Resolve aliases within the requested directory to their retained entry,
        # but never use a directory link to reach an unarchived file.
        requested = path
        for _ in range(16):
            path.relative_to(root)
            name = str(path.relative_to(dst))
            if not eligible(name) or not path.is_symlink() or path.parent.resolve(strict=True) != path.parent:
                return False
            next_path = Path(os.path.normpath(path.parent / path.readlink()))
            if next_path == target:
                break
            path = next_path
        else:
            return False
        other = str(target.relative_to(src))
        if not eligible(other):
            return False
        output_inventory = inventory(dst)
        entry = output_inventory.get(name, {})
        other_entry = inventory(src).get(other, {})
        if not all(isinstance(meta, dict) and not meta.get("is_dir") and meta.get("hash") for meta in (entry, other_entry)):
            return False
        # Private snapshot icons have a public cache policy. An alias may
        # reuse the captured icon bytes, never publish another private output.
        if requested.stem.lower() == "favicon":
            icon = output_inventory.get(str(requested.relative_to(dst)), {})
            return icon.get("hash") == other_entry["hash"]
        return True
    except (OSError, TypeError, ValueError, RuntimeError):
        return False
