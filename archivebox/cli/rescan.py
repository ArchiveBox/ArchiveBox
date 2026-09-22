"""Explicit discovery of portable snapshots; no checkpoint or default tree walk."""

import json
import os
import uuid
from itertools import groupby
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rich import print

from archivebox.config import CONSTANTS
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.misc.util import parse_date


def _directories(parent: Path):
    # Names encode dates / UUIDv7 creation time. Newest first within each
    # subtree, with bounded memory and no traversal into plugin payloads.
    with os.scandir(parent) as entries:
        paths = [Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False)]
    yield from sorted(paths, key=lambda path: path.name, reverse=True)


def _snapshot_directories(reverse=False):
    dates = []
    for user in _directories(CONSTANTS.USERS_DIR):
        root = user / CONSTANTS.SNAPSHOTS_DIR_NAME
        if root.is_symlink() or not root.is_dir():
            continue
        dates.extend(_directories(root))
    dates.sort(key=lambda path: path.name, reverse=not reverse)
    for _, date_group in groupby(dates, key=lambda path: path.name):
        directories = [directory for date in date_group for domain in _directories(date) for directory in _directories(domain)]
        yield from sorted(directories, key=lambda path: path.name, reverse=not reverse)


def _fields(record, names):
    return {name: record[name] for name in names.split() if name in record}


def _dates(record):
    return {name: parse_date(record[name]) for name in ("created_at", "modified_at") if record.get(name)}


def _restore_dates(obj, record):
    dates = _dates(record)
    if dates:
        type(obj).objects.filter(pk=obj.pk).update(**dates)
        for name, value in dates.items():
            setattr(obj, name, value)


def _reconcile_directory(directory: Path) -> str:
    snapshot_id = uuid.UUID(directory.name)
    snapshot = Snapshot.objects.select_related("crawl__created_by").filter(pk=snapshot_id).first()
    index = directory / CONSTANTS.JSONL_INDEX_FILENAME
    if index.is_symlink():
        raise ValueError("metadata must not be a symlink")
    if not index.exists():
        if snapshot is None or Path(snapshot.output_dir) != directory or snapshot.status != "sealed":
            raise ValueError("missing index.jsonl; cannot reconstruct an unknown or active snapshot")
        snapshot.write_index_jsonl(output_dir=directory)
        snapshot.reconcile_filesystem_links()
        return "Repaired"

    records = [json.loads(line) for line in index.read_text().splitlines() if line.strip()]
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("metadata records must be JSON objects")
    snapshots = [record for record in records if record.get("type") == "Snapshot"]
    if len(snapshots) != 1:
        raise ValueError("expected exactly one Snapshot record")
    record = snapshots[0]
    if uuid.UUID(record["id"]) != snapshot_id:
        raise ValueError("snapshot ID conflicts with directory name")
    if record.get("status") != "sealed":
        raise ValueError("snapshot is not sealed; finish the source capture first")
    if record.get("fs_version") not in {Snapshot._fs_current_version(), *Snapshot._FS_VERSION_MIGRATION_PATHS}:
        raise ValueError("unsupported filesystem version")
    crawl_id = uuid.UUID(record["crawl_id"])
    owner = directory.parents[3].name
    crawl_records = [item for item in records if item.get("type") == "Crawl" and uuid.UUID(item["id"]) == crawl_id]
    crawl_record = crawl_records[0] if crawl_records else {}
    if crawl_record.get("created_by", owner) != owner:
        raise ValueError("crawl owner conflicts with directory path")
    crawl = Crawl.objects.select_related("created_by").filter(pk=crawl_id).first()
    imported_crawl = crawl is None
    if crawl and crawl.created_by.username != owner:
        raise ValueError("existing crawl ID belongs to a different owner")
    if snapshot and (snapshot.url != record["url"] or snapshot.crawl_id != crawl_id or snapshot.timestamp != record["timestamp"]):
        raise ValueError("existing snapshot ID has conflicting identity; refusing to overwrite")
    if snapshot and Path(snapshot.output_dir) != directory:
        raise ValueError("existing snapshot has a different storage path")

    # Validate identities before inserting anything. Never turn an ID collision
    # into a new ID, and never overwrite a newer destination row.
    # write_index_jsonl retains historical hook records before appending the
    # canonical DB rows. The final record for each hook is authoritative.
    results = {(item.get("plugin"), item.get("hook_name", "")): item for item in records if item.get("type") == "ArchiveResult"}.values()
    pending = []
    for result in results:
        result_id = uuid.UUID(result["id"])
        if uuid.UUID(result["snapshot_id"]) != snapshot_id:
            raise ValueError("ArchiveResult belongs to another snapshot")
        existing = ArchiveResult.objects.filter(pk=result_id).first()
        identity = (snapshot_id, result["plugin"], result.get("hook_name", ""))
        if existing:
            if (existing.snapshot_id, existing.plugin, existing.hook_name) != identity:
                raise ValueError("existing ArchiveResult ID has conflicting identity")
        elif ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin=identity[1], hook_name=identity[2]).exists():
            raise ValueError("existing hook has a different ArchiveResult ID")
        else:
            pending.append(result)

    imported = snapshot is None
    if imported:
        if Snapshot.objects.filter(timestamp=record["timestamp"]).exists():
            raise ValueError("timestamp belongs to another snapshot")
        if Snapshot.objects.filter(crawl_id=crawl_id, url=record["url"]).exists():
            raise ValueError("crawl URL belongs to another snapshot")
        user, _ = get_user_model().objects.get_or_create(
            username=owner,
            defaults={"is_active": False, "password": "!"},
        )
        if crawl is None:
            # Old exports contain only crawl_id. Keep that identity but report
            # that absent crawl metadata cannot be reconstructed exactly.
            if not crawl_record:
                print(f"[yellow]    {directory}: no Crawl record; preserving ID with recovered metadata[/yellow]")
            crawl = Crawl(
                id=crawl_id,
                created_by=user,
                status="sealed",
                retry_at=None,
                **_fields(crawl_record, "urls max_depth config tags_str label"),
            )
            crawl.save(force_insert=True)
            _restore_dates(crawl, crawl_record)
        snapshot = Snapshot.create_from_directory(directory, crawl=crawl, preserve_identity=True)
        if snapshot is None:
            raise ValueError("invalid snapshot metadata")
        snapshot.status = "sealed"
        snapshot.retry_at = None
        if "config" not in record:
            snapshot.config = {"PERMISSIONS": "private"}
        if Path(snapshot.get_storage_path_for_version(Snapshot._fs_current_version())) != directory:
            raise ValueError("metadata does not match its owner/date/domain directory")
        snapshot.save(force_insert=True)
        _restore_dates(snapshot, record)

    # Each insert is durable. An interruption after the Snapshot insert is not
    # completion: the next pass still imports missing result IDs and tags.
    for result in pending:
        snapshot._create_archive_result_if_missing(result, {}, preserve_identity=True)
    tags_before = set(snapshot.tags.values_list("name", flat=True))
    snapshot._merge_tags_from_index(record)
    tags_changed = tags_before != set(snapshot.tags.values_list("name", flat=True))
    link = Path(snapshot.crawl.output_dir) / "snapshots" / snapshot.extract_domain_from_url(snapshot.url) / str(snapshot.id)
    links_ok = link.is_symlink() and link.resolve() == directory.resolve()
    if not links_ok:
        snapshot.reconcile_filesystem_links()
    if snapshot.fs_migration_needed:
        snapshot.migrate_filesystem_to_current_version(source_dir=directory)
    if imported:
        _restore_dates(snapshot, record)
    if imported_crawl:
        _restore_dates(crawl, crawl_record)
    # Leave source metadata untouched, including process/binary records that
    # are historical evidence rather than runnable destination process state.
    return "Imported" if imported else "Repaired" if pending or tags_changed or not links_ok else "Unchanged"


def reconcile_known_snapshots(snapshots, wait_for_turn=None):
    """Explicit metadata / asset repair; normal updates never call this scan."""
    for snapshot in snapshots.filter(status="sealed").paged_iterator():
        if wait_for_turn:
            wait_for_turn()
        if snapshot.fs_migration_needed:
            snapshot.migrate_filesystem_to_current_version()
        directory = Path(snapshot.output_dir)
        if not directory.is_dir():
            raise ValueError(f"Missing snapshot directory: {directory}")
        _reconcile_directory(directory)
        for result in snapshot.archiveresult_set.all():
            result.update_output_metadata_from_filesystem(snapshot_dir=directory, full_scan=True)


def rescan_snapshots(wait_for_turn=None, reverse=False, scan_legacy=None):
    stats = dict.fromkeys(("Imported", "Repaired", "Unchanged", "Errors"), 0)
    print("[*] Rescanning snapshot directories (O(N), orphans first; completed records are reused)...")
    known = {str(pk) for pk in Snapshot.objects.values_list("pk", flat=True)}
    # Two streaming passes avoid enumerating the entire archive before the
    # first import. Rows imported before interruption move to the second pass
    # next time; only one day's directory names are held in memory at a time.
    for existing in (False, True):
        if existing and scan_legacy:
            scan_legacy()
        for directory in _snapshot_directories(reverse=reverse):
            if (directory.name.replace("-", "") in known) != existing:
                continue
            if wait_for_turn:
                wait_for_turn()
            try:
                outcome = _reconcile_directory(directory)
                if directory.name.replace("-", "") in known:
                    for result in ArchiveResult.objects.filter(snapshot_id=uuid.UUID(directory.name)):
                        result.update_output_metadata_from_filesystem(snapshot_dir=directory, full_scan=True)
                stats[outcome] += 1
                if outcome != "Unchanged":
                    print(f"    {outcome}: {directory}")
            except (OSError, ValueError, KeyError, TypeError, ValidationError, IntegrityError) as err:
                stats["Errors"] += 1
                print(f"[yellow]    Unresolved: {directory}: {err}[/yellow]")
            if sum(stats.values()) % 100 == 0:
                print("    " + ", ".join(f"{key}: {value}" for key, value in stats.items()))
    print("    " + ", ".join(f"{key}: {value}" for key, value in stats.items()))
    if stats["Errors"]:
        raise SystemExit(1)
    return stats
