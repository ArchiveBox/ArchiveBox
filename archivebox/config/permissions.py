__package__ = "archivebox.config"

import os
import platform
import pwd
import socket
import stat
import subprocess
import sys
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import cast

from rich import print

#############################################################################################


def is_root_identity(running_uid: int, effective_uid: int) -> bool:
    return running_uid == 0 or effective_uid == 0


def select_archivebox_user(
    *,
    running_uid: int,
    running_gid: int,
    effective_uid: int,
    effective_gid: int,
    sudo_uid: int,
    sudo_gid: int,
    data_dir_uid: int,
    data_dir_gid: int,
    account_uid: int | None,
    account_gid: int | None,
    data_dir_owner_exists: bool = True,
) -> tuple[int, int]:
    if running_uid == 0:
        if data_dir_uid != 0 and data_dir_owner_exists:
            return data_dir_uid, data_dir_gid
        if account_uid is not None and account_gid is not None:
            return account_uid, account_gid

    return (
        effective_uid or running_uid or sudo_uid,
        effective_gid or running_gid or sudo_gid,
    )


DATA_DIR = Path(os.getcwd())

try:
    DATA_DIR_STAT = DATA_DIR.stat()
    DATA_DIR_UID = DATA_DIR_STAT.st_uid
    DATA_DIR_GID = DATA_DIR_STAT.st_gid
except PermissionError:
    DATA_DIR_UID = 0
    DATA_DIR_GID = 0

try:
    pwd.getpwuid(DATA_DIR_UID)
    DATA_DIR_OWNER_EXISTS = True
except KeyError:
    DATA_DIR_OWNER_EXISTS = False

DEFAULT_UID = 911
DEFAULT_GID = 911
RUNNING_AS_UID = os.getuid()
RUNNING_AS_GID = os.getgid()
EUID = os.geteuid()
EGID = os.getegid()
SUDO_UID = int(os.environ.get("SUDO_UID", "0"))
SUDO_GID = int(os.environ.get("SUDO_GID", "0"))
USER: str = Path("~").expanduser().resolve().name
HOSTNAME: str = cast(str, max([socket.gethostname(), platform.node()], key=len))

IS_ROOT = is_root_identity(RUNNING_AS_UID, EUID)
IN_DOCKER = os.environ.get("IN_DOCKER", "") in ("1", "true", "True", "TRUE", "yes")

FALLBACK_UID = RUNNING_AS_UID or SUDO_UID
FALLBACK_GID = RUNNING_AS_GID or SUDO_GID


def get_or_create_archivebox_account():
    try:
        account = pwd.getpwnam("archivebox")
    except KeyError:
        account = None

    if account is None and (RUNNING_AS_UID != 0 or platform.system() != "Linux"):
        return None

    if account is None:
        useradd = "/usr/sbin/useradd" if Path("/usr/sbin/useradd").exists() else "useradd"
        command = [
            useradd,
            "--system",
            "--create-home",
            "--home-dir",
            "/var/lib/archivebox",
            "--shell",
            "/bin/bash",
            "archivebox",
        ]
        try:
            subprocess.run(command, check=True)
        except (OSError, subprocess.CalledProcessError) as err:
            # Another concurrently starting process may have created it first.
            try:
                account = pwd.getpwnam("archivebox")
            except KeyError:
                raise RuntimeError(f"Failed to create the archivebox system user with: {' '.join(command)}") from err
        else:
            account = pwd.getpwnam("archivebox")

    if RUNNING_AS_UID == 0 and platform.system() == "Linux":
        # Package removal may preserve the account but remove its home. Repair
        # only this directory entry; never recursively chown existing data.
        account_home = Path(account.pw_dir)
        try:
            account_home.mkdir(parents=True, exist_ok=True)
            home_stat = account_home.stat()
            if (home_stat.st_uid, home_stat.st_gid) != (account.pw_uid, account.pw_gid):
                os.chown(account_home, account.pw_uid, account.pw_gid)
        except OSError as err:
            raise RuntimeError(f"Failed to prepare archivebox account home: {account_home}") from err

    return account


ARCHIVEBOX_ACCOUNT = get_or_create_archivebox_account()

ARCHIVEBOX_USER, ARCHIVEBOX_GROUP = select_archivebox_user(
    running_uid=RUNNING_AS_UID,
    running_gid=RUNNING_AS_GID,
    effective_uid=EUID,
    effective_gid=EGID,
    sudo_uid=SUDO_UID,
    sudo_gid=SUDO_GID,
    data_dir_uid=DATA_DIR_UID,
    data_dir_gid=DATA_DIR_GID,
    account_uid=ARCHIVEBOX_ACCOUNT.pw_uid if ARCHIVEBOX_ACCOUNT is not None else None,
    account_gid=ARCHIVEBOX_ACCOUNT.pw_gid if ARCHIVEBOX_ACCOUNT is not None else None,
    data_dir_owner_exists=DATA_DIR_OWNER_EXISTS,
)
if not USER:
    try:
        # alternative method 1 to get username
        USER = pwd.getpwuid(ARCHIVEBOX_USER).pw_name
    except (KeyError, OSError):
        USER = ""

if not USER:
    try:
        # alternative method 2 to get username
        import getpass

        USER = getpass.getuser()
    except OSError:
        USER = ""

if not USER:
    try:
        # alternative method 3 to get username
        USER = os.getlogin() or "archivebox"
    except OSError:
        USER = "archivebox"

ARCHIVEBOX_USER_EXISTS = False
try:
    pwd.getpwuid(ARCHIVEBOX_USER)
    ARCHIVEBOX_USER_EXISTS = True
except KeyError:
    ARCHIVEBOX_USER_EXISTS = False


ROOT_HANDOFF_NAMES = (
    ".archivebox_id",
    "ArchiveBox.conf",
    "index.sqlite3",
    "index.sqlite3-shm",
    "index.sqlite3-wal",
    "archive",
    "cache",
    "custom_plugins",
    "custom_templates",
    "lib",
    "logs",
    "personas",
    "sonic",
    "sources",
    "tmp",
    "users",
)


def root_data_dir_handoff_paths(data_dir: Path, argv: list[str]) -> tuple[Path, ...]:
    """Return bounded top-level paths safe to hand from root to archivebox."""

    data_dir = data_dir.resolve()
    if data_dir == Path("/"):
        return ()

    try:
        children = tuple(data_dir.iterdir())
    except (FileNotFoundError, PermissionError):
        return ()

    is_init = "init" in argv[1:]
    collection_exists = any((data_dir / marker).exists() for marker in (".archivebox_id", "ArchiveBox.conf", "index.sqlite3"))
    if not collection_exists and not (is_init and not children):
        return ()

    top_level_paths = tuple(data_dir / name for name in ROOT_HANDOFF_NAMES if (data_dir / name).exists())
    log_files = tuple((data_dir / "logs").glob("*.log"))
    return (data_dir, *top_level_paths, *log_files)


def root_should_handoff_data_dir(
    *,
    is_root: bool,
    data_dir_uid: int,
    account_uid: int | None,
    data_dir_owner_exists: bool = True,
) -> bool:
    """Allow bounded handoff only for root or archivebox-owned collection roots."""

    return is_root and account_uid is not None and (not data_dir_owner_exists or data_dir_uid in (0, account_uid))


def root_parent_can_grant_group_traversal(*, parent_uid: int, parent_gid: int, parent_mode: int, account_gid: int) -> bool:
    """Return whether adding archivebox traversal preserves existing parent access."""

    if parent_uid != 0 or parent_mode & stat.S_IXOTH:
        return False
    if parent_gid == account_gid:
        return not bool(parent_mode & stat.S_IXGRP)
    return not bool(parent_mode & stat.S_IRWXG)


def grant_archivebox_group_traversal(path: Path) -> None:
    """Let the archivebox account traverse private root-owned parents."""

    if not IS_ROOT or ARCHIVEBOX_ACCOUNT is None:
        return

    for parent in path.resolve().parents:
        if parent == Path("/"):
            continue
        parent_stat = parent.stat(follow_symlinks=False)
        if root_parent_can_grant_group_traversal(
            parent_uid=parent_stat.st_uid,
            parent_gid=parent_stat.st_gid,
            parent_mode=parent_stat.st_mode,
            account_gid=ARCHIVEBOX_ACCOUNT.pw_gid,
        ):
            os.chown(parent, -1, ARCHIVEBOX_ACCOUNT.pw_gid, follow_symlinks=False)
            os.chmod(parent, stat.S_IMODE(parent_stat.st_mode) | stat.S_IXGRP, follow_symlinks=False)


def handoff_root_owned_data_dir() -> None:
    account_uid = ARCHIVEBOX_ACCOUNT.pw_uid if ARCHIVEBOX_ACCOUNT is not None else None
    if not root_should_handoff_data_dir(
        is_root=IS_ROOT,
        data_dir_uid=DATA_DIR_UID,
        account_uid=account_uid,
        data_dir_owner_exists=DATA_DIR_OWNER_EXISTS,
    ):
        return

    handoff_paths = root_data_dir_handoff_paths(DATA_DIR, sys.argv)
    if not handoff_paths:
        return

    # Never walk collection contents. This only grants execute-only traversal
    # on private parents such as /root so the handed-off data remains reachable.
    grant_archivebox_group_traversal(DATA_DIR)

    for path in handoff_paths:
        try:
            os.chown(path, ARCHIVEBOX_ACCOUNT.pw_uid, ARCHIVEBOX_ACCOUNT.pw_gid, follow_symlinks=False)
        except (FileNotFoundError, PermissionError):
            pass


#############################################################################################


def drop_privileges():
    """If running as root, drop privileges to the data dir owner or archivebox user."""

    # Root-owned uv tools commonly live below /root. Keep the installed package
    # importable after dropping EUID without changing ownership of the tool env.
    grant_archivebox_group_traversal(Path(__file__))
    handoff_root_owned_data_dir()

    # Always run ArchiveBox as the user that owns the data dir, or as the
    # archivebox service account when the data dir is root-owned.
    if os.geteuid() == 0 and ARCHIVEBOX_USER != 0 and ARCHIVEBOX_USER_EXISTS:
        pw_record = pwd.getpwuid(ARCHIVEBOX_USER)
        os.initgroups(pw_record.pw_name, ARCHIVEBOX_GROUP)
        if os.getegid() != ARCHIVEBOX_GROUP:
            os.setegid(ARCHIVEBOX_GROUP)
        if os.geteuid() != ARCHIVEBOX_USER:
            os.seteuid(ARCHIVEBOX_USER)

        # update environment variables so that subprocesses dont try to write to /root
        os.environ["HOME"] = pw_record.pw_dir
        os.environ["LOGNAME"] = pw_record.pw_name
        os.environ["USER"] = pw_record.pw_name
        os.environ["XDG_CACHE_HOME"] = str(Path(pw_record.pw_dir) / ".cache")
        os.environ["XDG_CONFIG_HOME"] = str(Path(pw_record.pw_dir) / ".config")
        os.environ["XDG_DATA_HOME"] = str(Path(pw_record.pw_dir) / ".local" / "share")
        os.environ.pop("XDG_RUNTIME_DIR", None)
        os.environ.pop("ABXBUS_MULTIPROCESS_SEMAPHORE_DIR", None)

        semaphore_dir = Path(pw_record.pw_dir) / ".cache" / "abxbus" / "semaphores"
        os.environ["ABXBUS_MULTIPROCESS_SEMAPHORE_DIR"] = str(semaphore_dir)

        with suppress(ImportError):
            from abxbus import retry as abxbus_retry

            abxbus_retry.MULTIPROCESS_SEMAPHORE_DIR = semaphore_dir

    if ARCHIVEBOX_USER == 0 or not ARCHIVEBOX_USER_EXISTS:
        print(
            "[yellow]:warning:  Running as [red]root[/red] is not recommended and may make your [blue]DATA_DIR[/blue] inaccessible to other users on your system.[/yellow] (use [blue]sudo[/blue] instead)",
            file=sys.stderr,
        )


@contextmanager
def SudoPermission(uid=0, fallback=False):
    """Attempt to run code with sudo permissions for a given user (or root)"""

    if os.geteuid() == uid:
        # no need to change effective UID, we are already that user
        yield
        return

    try:
        # change our effective UID to the given UID
        os.seteuid(uid)
    except PermissionError as err:
        if not fallback:
            raise PermissionError(f"Not enough permissions to run code as uid={uid}, please retry with sudo") from err
    try:
        # yield back to the caller so they can run code inside context as root
        yield
    finally:
        # then set effective UID back to DATA_DIR owner
        try:
            os.seteuid(ARCHIVEBOX_USER)
        except PermissionError as err:
            if not fallback:
                raise PermissionError(f"Failed to revert uid={uid} back to {ARCHIVEBOX_USER} after running code with sudo") from err
