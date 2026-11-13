"""Primary archive storage through rclone FUSE and the native Process lifecycle."""

import configparser
import fcntl
import os
import shlex
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from abxpkg import Binary

from archivebox.config.constants import CONSTANTS
from archivebox.machine.models import Machine, Process, PROCESS_STDOUT_FILE_KEY, PROCESS_STDERR_FILE_KEY
from archivebox.uuid_compat import uuid7

from .install import OfficialRcloneProvider


class StorageUnavailable(OSError):
    pass


def private_dir():
    path = CONSTANTS.DATA_DIR / "storage"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def settings():
    machine = Machine.current_readonly()
    return (machine.config or {}) if machine else {}


def update_settings(**values):
    machine = Machine.current()
    machine.refresh_from_db(fields=["config"])
    machine.config = {**(machine.config or {}), **values}
    machine.save(update_fields=["config", "modified_at"])


def config_path(revision=None):
    revision = revision or settings().get("ARCHIVE_STORAGE_REVISION", "")
    if not revision or len(revision) != 32 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("Save a storage connection first.")
    return private_dir() / f"rclone.{revision}.conf"


def read_config(revision=None):
    try:
        path = config_path(revision)
    except ValueError:
        return {}, {}
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)
    return dict(parser["archivebox-storage"]), dict(parser["archivebox"])


def write_config(metadata, options):
    revision = uuid7().hex
    parser = configparser.ConfigParser(interpolation=None)
    parser["archivebox-storage"] = metadata
    parser["archivebox"] = options
    with tempfile.NamedTemporaryFile(mode="w", dir=private_dir(), delete=False) as output:
        parser.write(output)
        temporary = Path(output.name)
    temporary.chmod(0o600)
    temporary.replace(config_path(revision))
    update_settings(ARCHIVE_STORAGE_REVISION=revision, ARCHIVE_STORAGE_CHECKED="")
    return revision


def mount_path(revision):
    return private_dir() / "mounts" / revision


def assert_archive_available():
    """Never fall back to the empty underlying directory after a lost mount."""
    archive = CONSTANTS.ARCHIVE_DIR
    active = settings().get("ARCHIVE_STORAGE_ACTIVE", "")
    if archive.is_symlink():
        target = Path(os.path.abspath(archive.parent / os.readlink(archive)))
        if target.parent == private_dir() / "mounts":
            if not os.path.ismount(target):
                raise StorageUnavailable("Archive storage is disconnected. Reconnect it in Storage before capturing or replaying pages.")
            return
    if active:
        raise StorageUnavailable("Archive storage cutover is incomplete. Reconnect it in Storage; the previous archive has been preserved.")


@contextmanager
def archive_access(*, exclusive=False):
    """Shared capture/delete access; exclusive collection-wide filesystem cutover.

    The existing per-crawl locks cannot exclude *all* writers while allowing
    normal parallel captures. This local flock is independent of DB transactions.
    Always acquire it, including before remote storage is first configured.
    """
    with (private_dir() / "archive.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            if not exclusive:
                assert_archive_available()
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def managed_binary(*, install=False):
    root = private_dir() / "rclone"
    command = shlex.join([sys.executable, str(Path(__file__).with_name("install.py"))]) + ' "$BIN_DIR/rclone"'
    binary = Binary(name="rclone", binproviders=[OfficialRcloneProvider(install_root=root)], overrides={"bash": {"install": command}})
    binary = binary.install() if install else binary.load()
    if not binary or not binary.loaded_abspath:
        raise RuntimeError("Install rclone from Storage before checking or activating storage.")
    return str(binary.loaded_abspath)


def processes():
    return Process.objects.filter(machine=Machine.current(), worker_type__in=["storage", "storage-mount"]).order_by("-created_at")


def active_operation():
    for process in processes().filter(worker_type="storage", status="running"):
        process.poll()
        if process.status == "running":
            return process
    return None


@contextmanager
def configuration_access():
    from archivebox.crawls.locks import _lifecycle_lock

    with _lifecycle_lock("storage-config", private_dir() / "config.lock"):
        yield


def launch_operation(action, *, background=True):
    if action not in {"install", "check", "activate", "reconnect"}:
        raise ValueError("Unknown storage operation.")
    # Serialize configuration publication and process launch, not a DB transaction.
    with configuration_access():
        if active_operation():
            raise ValueError("Wait for the current storage operation to finish.")
        revision = settings().get("ARCHIVE_STORAGE_REVISION", "")
        if action != "install":
            config_path(revision)
        process = Process.objects.create(
            machine=Machine.current(),
            process_type="cli",
            worker_type="storage",
            pwd=str(CONSTANTS.DATA_DIR),
            cmd=[sys.executable, "-m", "archivebox", "manage", "storage", action, "--revision", revision],
            env={"DATA_DIR": str(CONSTANTS.DATA_DIR)},
            timeout=3600,
        )
        log_dir = private_dir() / "processes" / str(process.pk)
        process.env.update({PROCESS_STDOUT_FILE_KEY: str(log_dir / "stdout.log"), PROCESS_STDERR_FILE_KEY: str(log_dir / "stderr.log")})
        process.save(update_fields=["env"])
        process.launch(background=background)
        return process


def _rclone(revision, arguments, *, background=False, timeout=3600):
    # Native Process is the only lifecycle record; credentials never enter argv.
    process = Process.objects.create(
        machine=Machine.current(),
        parent=Process.current(),
        process_type="binary",
        worker_type="storage-mount" if background else "storage-command",
        pwd=str(private_dir()),
        timeout=0 if background else timeout,
        cmd=[managed_binary(), "--config", str(config_path(revision)), "--retries", "1", "--low-level-retries", "1", *arguments],
    )
    log_dir = private_dir() / "processes" / str(process.pk)
    process.env = {PROCESS_STDOUT_FILE_KEY: str(log_dir / "stdout.log"), PROCESS_STDERR_FILE_KEY: str(log_dir / "stderr.log")}
    process.save(update_fields=["env"])
    process.launch(background=background)
    if not background and process.exit_code:
        raise RuntimeError(
            f"rclone {arguments[0]} failed. Inspect Process {process.pk} for the server error; the original archive is preserved.",
        )
    return process


def check_connection(revision):
    metadata, _options = read_config(revision)
    remote = f"archivebox:{metadata['path'].rstrip('/')}"
    with tempfile.TemporaryDirectory(prefix="check-", dir=private_dir()) as temporary:
        probe = Path(temporary) / "probe"
        probe.write_text(f"ArchiveBox storage check {uuid7().hex}\n")
        target = f"{remote}/.archivebox-check-{uuid7().hex}"
        _rclone(revision, ["copyto", str(probe), target], timeout=120)
        try:
            restored = Path(temporary) / "restored"
            _rclone(revision, ["copyto", target, str(restored)], timeout=120)
            if restored.read_bytes() != probe.read_bytes():
                raise RuntimeError("The storage read-back did not match the written bytes.")
        finally:
            _rclone(revision, ["deletefile", target], timeout=120)
    if settings().get("ARCHIVE_STORAGE_REVISION") == revision:
        update_settings(ARCHIVE_STORAGE_CHECKED=revision)


def ensure_mount(revision):
    target = mount_path(revision)
    if os.path.ismount(target):
        return target
    target.mkdir(parents=True, exist_ok=True)
    # fusermount requires a writable mountpoint. Retain an fd to the underlying
    # directory so it can be made read-only *after* mounting, without changing
    # the remote root permissions. On unmount, local writes then fail closed.
    target.chmod(0o700)
    underlying = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
    try:
        metadata, _options = read_config(revision)
        process = _rclone(
            revision,
            [
                "mount",
                "--allow-other",
                "--default-permissions",
                "--uid",
                str(os.geteuid()),
                "--gid",
                str(os.getegid()),
                f"archivebox:{metadata['path']}",
                str(target),
                "--vfs-cache-mode",
                "full",
                "--vfs-write-back",
                "0s",
                "--links",
                "--cache-dir",
                str(private_dir() / "cache" / revision),
                "--dir-cache-time",
                "5s",
                "--file-perms",
                "0600",
                "--dir-perms",
                "0700",
            ],
            background=True,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if os.path.ismount(target):
                return target
            if process.poll() is not None:
                raise RuntimeError(
                    "Archive mount failed. Install/enable FUSE on the server; Docker needs /dev/fuse and SYS_ADMIN. See the mount Process log.",
                )
            time.sleep(0.1)
        process.kill()
        raise RuntimeError("Archive mount did not become available. Check FUSE permissions and the mount Process log.")
    finally:
        os.fchmod(underlying, 0o500)
        os.close(underlying)


def activate(revision):
    with archive_access(exclusive=True):
        if settings().get("ARCHIVE_STORAGE_REVISION") != revision:
            raise ValueError("The connection changed before activation. Check and activate the current connection.")
        if settings().get("ARCHIVE_STORAGE_ACTIVE") == revision:
            reconnect(revision)
            return
        assert_archive_available()
        check_connection(revision)
        archive = CONSTANTS.ARCHIVE_DIR
        metadata, _options = read_config(revision)
        remote = f"archivebox:{metadata['path']}"
        # --immutable refuses to replace a differing existing remote file.
        # --download checks actual bytes even on providers without hashes.
        _rclone(revision, ["copy", str(archive), remote, "--immutable", "--links"])
        _rclone(revision, ["check", str(archive), remote, "--download", "--one-way", "--links"])
        target = ensure_mount(revision)
        backup = CONSTANTS.DATA_DIR / f"archive.before-storage-{uuid7().hex}"
        temporary = CONSTANTS.DATA_DIR / f".archive-next-{uuid7().hex}"
        temporary.symlink_to(target.relative_to(CONSTANTS.DATA_DIR), target_is_directory=True)
        previous_active = settings().get("ARCHIVE_STORAGE_ACTIVE", "")
        # Durable recovery information is published before the only rename gap.
        update_settings(ARCHIVE_STORAGE_ACTIVE=revision, ARCHIVE_STORAGE_PREVIOUS=str(backup))
        try:
            archive.rename(backup)
            temporary.replace(archive)
        except BaseException:
            if not archive.exists() and not archive.is_symlink() and (backup.exists() or backup.is_symlink()):
                backup.rename(archive)
            update_settings(ARCHIVE_STORAGE_ACTIVE=previous_active)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        assert_archive_available()


def reconnect(revision):
    active = settings().get("ARCHIVE_STORAGE_ACTIVE")
    if active != revision:
        raise ValueError("Only the active archive connection can be reconnected.")
    target = ensure_mount(revision)
    archive = CONSTANTS.ARCHIVE_DIR
    if not archive.exists() and not archive.is_symlink():
        # Recovery after interruption between verified-source rename and cutover.
        previous = Path(settings().get("ARCHIVE_STORAGE_PREVIOUS", ""))
        if previous.parent != CONSTANTS.DATA_DIR or not previous.name.startswith("archive.before-storage-") or not previous.exists():
            raise StorageUnavailable("The preserved archive cannot be found. Restore the archive path before continuing.")
        archive.symlink_to(target.relative_to(CONSTANTS.DATA_DIR), target_is_directory=True)
    assert_archive_available()


def restore_archive_mount():
    """Reconnect once at native runner startup; never fall back to local writes."""
    if not settings().get("ARCHIVE_STORAGE_ACTIVE"):
        return
    try:
        assert_archive_available()
        return
    except StorageUnavailable:
        process = launch_operation("reconnect", background=False)
        if process.exit_code != 0:
            raise StorageUnavailable("Primary archive storage could not reconnect. Check Storage and the reconnect Process log.")
    assert_archive_available()
