__package__ = "archivebox.config"

import os
import platform
import pwd
import socket
import sys
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import cast

from rich import print

#############################################################################################


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
) -> tuple[int, int]:
    if running_uid == 0:
        if data_dir_uid != 0:
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

IS_ROOT = RUNNING_AS_UID == 0
IN_DOCKER = os.environ.get("IN_DOCKER", "") in ("1", "true", "True", "TRUE", "yes")

FALLBACK_UID = RUNNING_AS_UID or SUDO_UID
FALLBACK_GID = RUNNING_AS_GID or SUDO_GID
try:
    ARCHIVEBOX_ACCOUNT = pwd.getpwnam("archivebox")
except KeyError:
    ARCHIVEBOX_ACCOUNT = None

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

    return (data_dir, *(data_dir / name for name in ROOT_HANDOFF_NAMES if (data_dir / name).exists()))


def handoff_root_owned_data_dir() -> None:
    if not (IS_ROOT and DATA_DIR_UID == 0 and ARCHIVEBOX_ACCOUNT is not None):
        return

    for path in root_data_dir_handoff_paths(DATA_DIR, sys.argv):
        try:
            os.chown(path, ARCHIVEBOX_ACCOUNT.pw_uid, ARCHIVEBOX_ACCOUNT.pw_gid, follow_symlinks=False)
        except (FileNotFoundError, PermissionError):
            pass


#############################################################################################


def drop_privileges():
    """If running as root, drop privileges to the data dir owner or archivebox user."""

    handoff_root_owned_data_dir()

    # Always run ArchiveBox as the user that owns the data dir, or as the
    # archivebox service account when the data dir is root-owned.
    if os.getuid() == 0 and ARCHIVEBOX_USER != 0 and ARCHIVEBOX_USER_EXISTS:
        pw_record = pwd.getpwuid(ARCHIVEBOX_USER)
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
