"""Read-only path diagnostics from the kernel mount table; no remote filesystem probes."""

import os
import stat
from pathlib import Path

import psutil
from django.db import connection

from archivebox.config.common import get_config
from archivebox.config.constants import CONSTANTS

# Keep the Linux local set consistent with _default_sqlite_journal_mode.
LOCAL_FILESYSTEMS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "overlay", "tmpfs", "f2fs", "apfs", "hfs", "hfsplus", "ufs", "ramfs"}
NETWORK_FILESYSTEMS = {
    "nfs",
    "nfs4",
    "cifs",
    "smbfs",
    "smb3",
    "sshfs",
    "fuse.sshfs",
    "davfs",
    "davfs2",
    "fuse.davfs",
    "ceph",
    "glusterfs",
    "fuse.glusterfs",
    "afs",
}
SHARED_FILESYSTEMS = {"9p", "virtiofs", "fuse.virtiofs", "vboxsf", "hgfs", "fuse.vmhgfs-fuse"}


def inspect_storage(metadata, storage_settings, unavailable=""):
    """Inspect local metadata only; network/unknown mounts never receive stat/access/statvfs calls."""
    try:
        mounts = sorted(psutil.disk_partitions(all=True), key=lambda item: len(Path(item.mountpoint).parts), reverse=True)
    except OSError:
        mounts = []
    runtime = get_config(resolve_plugins=False)
    data = CONSTANTS.DATA_DIR
    active = storage_settings.get("ARCHIVE_STORAGE_ACTIVE")
    managed = data / "storage" / "mounts" / active if active else None

    def mount_for(path):
        return next((item for item in mounts if path.is_relative_to(Path(item.mountpoint))), None)

    def locality(mount):
        filesystem = mount.fstype.lower() if mount else ""
        if filesystem in LOCAL_FILESYSTEMS:
            return "Local"
        if filesystem in NETWORK_FILESYSTEMS:
            return "Network"
        if filesystem in SHARED_FILESYSTEMS:
            return "VM/shared"
        return "Unknown"

    def resolve_local(path):
        # Resolve symlinks only on native local filesystems. Once a remote mount
        # is reached, leave its suffix lexical: diagnosing it must not wake it.
        pending = list(Path(os.path.abspath(path)).parts[1:])
        current = Path("/")
        links = 0
        while pending:
            current /= pending.pop(0)
            if locality(mount_for(current)) != "Local":
                return current.joinpath(*pending)
            try:
                if stat.S_ISLNK(current.lstat().st_mode):
                    links += 1
                    if links > 40:
                        raise OSError("Symlink loop")
                    target = Path(os.readlink(current))
                    target = target if target.is_absolute() else current.parent / target
                    pending = list(Path(os.path.abspath(target)).parts[1:]) + pending
                    current = Path("/")
            except FileNotFoundError:
                return current.joinpath(*pending)
        return current

    free_by_mount = {}
    rows = []
    sqlite_network_paths = []

    def add(label, path, *, local_required=True, optional=False, sqlite=False):
        path = Path(os.path.abspath(path))
        error = ""
        try:
            resolved = resolve_local(path)
        except OSError as exc:
            resolved, error = path, str(exc)
        mount = mount_for(resolved)
        kind = locality(mount)
        managed_path = managed and resolved.is_relative_to(managed)
        if managed_path:
            if metadata.get("provider") in {"drive", "s3"}:
                kind = "Network"
            elif metadata.get("provider") == "local":
                try:
                    kind = locality(mount_for(resolve_local(Path(metadata["path"]))))
                except (OSError, KeyError):
                    kind = "Unknown"
        row = {
            "label": label,
            "path": str(path),
            "resolved": str(resolved),
            "locality": kind,
            "filesystem": mount.fstype if mount else "Unknown",
            "mount": mount.mountpoint if mount else "Unknown",
            # Never expose mount credentials or signed URL parameters.
            "source": mount.device.rsplit("@", 1)[-1].split("?", 1)[0] if mount else "Unknown",
            "owner": "—",
            "size": None,
            "used": None,
            "total": None,
            "permissions": "Not probed",
            "free": None,
            "status": "Mounted" if mount else "Unknown",
            "severity": "",
        }
        if local_required and kind != "Local":
            row.update(status="Local storage required", severity="warning")
        if sqlite and kind == "Network" and not optional:
            row.update(status="Unsafe SQLite location", severity="danger")
            sqlite_network_paths.append(row)
        if error:
            row.update(status="Path unavailable", severity="warning")
        elif managed_path and unavailable:
            row.update(status="Disconnected", severity="danger", permissions="Unavailable", filesystem="rclone (unmounted)")
        elif kind == "Local":
            try:
                info = resolved.stat()
                readable = os.access(resolved, os.R_OK, effective_ids=True)
                writable = os.access(resolved, os.W_OK, effective_ids=True)
                row["permissions"] = (
                    f"{stat.S_IMODE(info.st_mode):04o} · {'RW' if readable and writable else 'R' if readable else 'No access'}"
                )
                row["owner"] = f"{info.st_uid}:{info.st_gid}"
                row["size"] = info.st_size if stat.S_ISREG(info.st_mode) else None
                row["status"] = "Ready" if readable and writable else "Read-only" if readable else "No access"
                if not writable:
                    row["severity"] = "warning"
                key = info.st_dev
                if key not in free_by_mount:
                    free_by_mount[key] = psutil.disk_usage(resolved)
                usage = free_by_mount[key]
                row.update(free=usage.free, used=usage.used, total=usage.total)
            except FileNotFoundError:
                row.update(status="Not created" if optional else "Missing", severity="" if optional else "warning", permissions="—")
            except OSError:
                row.update(status="Unavailable", severity="warning")
        rows.append(row)
        return row

    add("Collection data", data)
    add("Primary archive", CONSTANTS.ARCHIVE_DIR, local_required=False)
    if connection.vendor == "sqlite":
        database = Path(connection.settings_dict["NAME"])
        add("Active SQLite database", database, sqlite=True)
        add("SQLite WAL", str(database) + "-wal", sqlite=True, optional=True)
        add("SQLite shared memory", str(database) + "-shm", sqlite=True, optional=True)
    else:
        # Database servers are not archive mounts; show endpoint fields only,
        # never a DSN, password, or connection OPTIONS.
        db = connection.settings_dict
        rows.append(
            {
                "label": "Active database server",
                "path": str(db.get("NAME", "")),
                "resolved": str(db.get("NAME", "")),
                "locality": "Database server",
                "filesystem": connection.vendor,
                "mount": "—",
                "source": str(db.get("HOST") or "Local socket"),
                "permissions": "Database connection",
                "status": "Connected",
                "severity": "",
                "free": None,
                "total": None,
                "size": None,
                "owner": "—",
            },
        )
    conventional = data / "index.sqlite3"
    actual_database = os.path.abspath(connection.settings_dict["NAME"]) if connection.vendor == "sqlite" else None
    if actual_database != str(conventional):
        # Do not stat a default index on remote data just to decide whether
        # to show it. Its expected location is diagnostic information too.
        try:
            local_data = locality(mount_for(resolve_local(data))) == "Local"
        except OSError:
            local_data = False
        if not local_data or os.path.lexists(conventional):
            add(
                "Additional index.sqlite3 (not active)" if local_data else "Additional index.sqlite3 (presence unknown)",
                conventional,
                sqlite=True,
                optional=not local_data,
            )
    for label, path, optional in (
        ("Configuration", CONSTANTS.CONFIG_FILE, False),
        ("Browser profiles", CONSTANTS.PERSONAS_DIR, False),
        ("Logs", CONSTANTS.LOGS_DIR, False),
        ("Import sources", CONSTANTS.SOURCES_DIR, False),
        ("Temporary files", runtime.TMP_DIR, False),
        ("Installed binaries", runtime.ABXPKG_LIB_DIR, False),
        ("rclone credentials", data / "storage", True),
        ("rclone write cache", data / "storage" / "cache", True),
    ):
        add(label, path, optional=optional)
    if managed:
        add("Managed mount", managed, local_required=False)
    if storage_settings.get("ARCHIVE_STORAGE_PREVIOUS"):
        add("Preserved archive (before cutover)", storage_settings["ARCHIVE_STORAGE_PREVIOUS"], local_required=False)
    return {"rows": rows, "sqlite_network_paths": sqlite_network_paths, "database_vendor": connection.vendor}
