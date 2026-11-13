"""Collection storage reports from native snapshots, hash manifests, and Process logs."""

import hashlib
import json
import re
import stat
import sys
from collections import defaultdict
from pathlib import Path

from django.utils import timezone

from archivebox.config import CONSTANTS
from archivebox.core.models import Snapshot
from archivebox.machine.models import Machine, Process


def file_digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def output_file(snapshot, relative):
    relative = Path(relative)
    if relative.is_absolute() or any(
        part in {"..", ".persona", ".abx-dl", "chrome_profile", "archivebox-extensions"} for part in relative.parts
    ):
        raise ValueError("Not a retained capture output.")
    if relative == Path("index.jsonl") or (
        relative.parent == Path("chrome")
        and relative.name
        in {
            "cdp_url.txt",
            "target_id.txt",
            "chrome.pid",
            "browser.json",
            "url.txt",
            "navigation.json",
        }
    ):
        raise ValueError("Mutable capture runtime records are not retained file candidates.")
    root = snapshot.output_dir.resolve(strict=True)
    root.relative_to(CONSTANTS.ARCHIVE_DIR.resolve())
    path = root / relative
    if path.is_symlink():
        raise ValueError("Symlinks are not duplicate-file candidates.")
    resolved = path.resolve(strict=True).relative_to(root)
    if any(part in {".persona", ".abx-dl", "chrome_profile", "archivebox-extensions"} for part in resolved.parts):
        raise ValueError("Browser runtime files are not capture outputs.")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Not a regular file.")
    return path, info


def audit_files(snapshots):
    groups = defaultdict(list)
    report = {
        "complete": False,
        "snapshots": 0,
        "hashed_snapshots": 0,
        "output_manifests": 0,
        "missing_manifests": 0,
        "stale_files": 0,
        "files": 0,
        "bytes": 0,
        "groups": [],
    }
    pending = snapshots.filter(status=Snapshot.StatusChoices.SEALED)
    while True:
        # Materialize each database batch before opening or hashing any files.
        batch = list(pending.order_by("pk")[:100])
        if not batch:
            break
        pending = snapshots.filter(status=Snapshot.StatusChoices.SEALED, pk__gt=batch[-1].pk)
        for snapshot in batch:
            report["snapshots"] += 1
            manifest = snapshot.output_dir / "hashes" / "hashes.json"
            if manifest.exists():
                try:
                    expected = manifest.with_name("hashes.sha256").read_text().strip()
                    if not re.fullmatch("[0-9a-f]{64}", expected) or file_digest(manifest) != expected:
                        raise ValueError("Hash manifest is incomplete or changed.")
                    entries = snapshot.hashes_index
                except (OSError, ValueError):
                    report["missing_manifests"] += 1
                    continue
                report["hashed_snapshots"] += 1
            else:
                # Older/partial captures may never have run the hashes plugin. Their
                # normal output manifests still identify retained files; hash those
                # bytes read-only rather than launching an extractor from an audit.
                entries = {}
                for result in snapshot.archiveresult_set.filter(status="succeeded"):
                    for name, metadata in result.output_file_map().items():
                        relative = result.output_file_path(name)
                        if relative and metadata.get("type") != "directory":
                            entries[relative] = {"size": metadata.get("size"), "hash": None}
                report["output_manifests"] += 1
                if not entries:
                    report["missing_manifests"] += 1
            for relative, metadata in entries.items():
                expected_hash = metadata.get("hash")
                digest = str(expected_hash or "")
                if metadata.get("is_dir") or (
                    expected_hash is not None and (not re.fullmatch("[0-9a-f]{64}", digest) or digest == "0" * 64)
                ):
                    continue
                try:
                    path, info = output_file(snapshot, relative)
                    digest = file_digest(path)
                    if (metadata["size"] is not None and info.st_size != int(metadata["size"])) or (
                        expected_hash is not None and digest != expected_hash
                    ):
                        raise ValueError("Saved bytes changed since the hash manifest.")
                except (OSError, RuntimeError, ValueError, TypeError):
                    report["stale_files"] += 1
                    continue
                report["files"] += 1
                report["bytes"] += info.st_size
                if info.st_size:
                    groups[(digest, info.st_size)].append(
                        {
                            "snapshot_id": str(snapshot.pk),
                            "url": snapshot.url,
                            "title": snapshot.title or snapshot.url,
                            "captured_at": snapshot.created_at.isoformat(),
                            "path": str(relative),
                            "absolute_path": str(path),
                            "device": info.st_dev,
                            "inode": info.st_ino,
                        },
                    )
    for (digest, size), files in groups.items():
        if len(files) < 2:
            continue
        devices = defaultdict(set)
        for entry in files:
            devices[entry["device"]].add(entry["inode"])
        potential = sum(max(len(inodes) - 1, 0) * size for inodes in devices.values())
        report["groups"].append(
            {
                "id": f"{digest}:{size}",
                "hash": digest,
                "size": size,
                "files": files,
                "potential_bytes": potential,
                "urls": len({entry["url"] for entry in files}),
                "captures": len({entry["snapshot_id"] for entry in files}),
            },
        )
    report["groups"].sort(key=lambda group: (-group["potential_bytes"], group["id"]))
    report.update(
        complete=True,
        potential_bytes=sum(group["potential_bytes"] for group in report["groups"]),
        checked_at=timezone.now().isoformat(),
    )
    return report


def filter_groups(groups, query):
    if not query:
        return groups
    return [group for group in groups if any(query.casefold() in entry["url"].casefold() for entry in group["files"])]


def group_extensions(groups):
    """Attribute each reclaimable inode once, retaining whole groups for review."""
    extensions = {}
    for group in groups:
        if not group["potential_bytes"]:
            continue
        seen = defaultdict(set)
        members = defaultdict(list)
        savings = defaultdict(int)
        for entry in sorted(group["files"], key=lambda item: (item["path"], item["snapshot_id"])):
            extension = Path(entry["path"]).suffix.lower() or "(none)"
            members[extension].append(entry)
            inodes = seen[entry["device"]]
            if entry["inode"] not in inodes:
                if inodes:
                    savings[extension] += group["size"]
                inodes.add(entry["inode"])
        for extension, files in members.items():
            row = extensions.setdefault(
                extension, {"extension": extension, "file_count": 0, "group_count": 0, "potential_bytes": 0, "groups": []}
            )
            row["file_count"] += len(files)
            row["group_count"] += 1
            row["potential_bytes"] += savings[extension]
            row["groups"].append(group)
    return sorted(
        (row for row in extensions.values() if row["potential_bytes"]), key=lambda row: (-row["potential_bytes"], row["extension"])
    )


def group_selection_hash(groups):
    return hashlib.sha256(json.dumps(sorted(group["id"] for group in groups)).encode()).hexdigest()


def apply_cow(groups):
    """Revalidate exact bytes, then use the existing hashes plugin's CoW helper."""
    if sys.platform != "linux":
        raise ValueError("Native copy-on-write deduplication currently requires Linux and a supporting filesystem. No files changed.")
    from abx_plugins.plugins.hashes.files import deduplicate_files

    devices = defaultdict(list)
    # Validate the entire approved selection before the first extent operation.
    for group in groups:
        for entry in group["files"]:
            snapshot = Snapshot.objects.get(pk=entry["snapshot_id"], status=Snapshot.StatusChoices.SEALED)
            if snapshot.archiveresult_set.filter(status__in=["queued", "started"]).exists():
                raise ValueError("A selected capture is being updated; scan again after it finishes.")
            path, info = output_file(snapshot, entry["path"])
            if info.st_size != group["size"] or file_digest(path) != group["hash"]:
                raise ValueError("A selected file changed after the audit. No files changed; run a new audit.")
            devices[info.st_dev].append(
                {"path": str(path.relative_to(CONSTANTS.ARCHIVE_DIR.resolve())), "hash": group["hash"], "size": group["size"]},
            )
    total = {"supported_platform": True, "attempted_files": 0, "extent_bytes_verified": 0, "failed_files": 0}
    for files in devices.values():
        result = deduplicate_files(CONSTANTS.ARCHIVE_DIR.resolve(), files)
        for key in ("attempted_files", "extent_bytes_verified", "failed_files"):
            total[key] += result[key]
    return total


def launch(*, user_id, source=None, group_ids=None, extension=None, selection_hash=None, query=""):
    process = Process(machine=Machine.current(), process_type=Process.TypeChoices.CLI, worker_type="storage-audit", timeout=0)
    directory = CONSTANTS.DATA_DIR / "logs" / "storage-audit" / str(process.pk)
    directory.mkdir(parents=True, exist_ok=False)
    process.pwd = str(directory)
    process.cmd = [sys.executable, "-m", "archivebox", "manage", "storageaudit", "--user", str(user_id), "--process-id", str(process.pk)]
    if source is not None:
        process.cmd.extend(["--source", str(source.pk)])
        if extension is not None:
            process.cmd.extend(["--extension", extension, "--selection-hash", selection_hash])
            if query:
                process.cmd.extend(["--query", query])
        else:
            for group_id in group_ids or []:
                process.cmd.extend(["--group", group_id])
    process.save()
    return process.launch(background=True, cwd=str(CONSTANTS.DATA_DIR))


def read_report(process):
    path = process.stdout_file
    result = {}
    if path and path.is_file():
        with path.open(errors="replace") as source:
            for line in source:
                if not line.startswith("{"):
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    result = entry
    return result
