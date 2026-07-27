__package__ = "archivebox.config"

import os
import pwd
import sys
import socket
import platform
from typing import cast

from rich import print

from pathlib import Path
from contextlib import contextmanager

#############################################################################################

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
SUDO_UID = int(os.environ.get("SUDO_UID", 0))
SUDO_GID = int(os.environ.get("SUDO_GID", 0))
USER: str = Path("~").expanduser().resolve().name
HOSTNAME: str = cast(str, max([socket.gethostname(), platform.node()], key=len))

IS_ROOT = RUNNING_AS_UID == 0
IN_DOCKER = os.environ.get("IN_DOCKER", False) in ("1", "true", "True", "TRUE", "yes")

FALLBACK_UID = RUNNING_AS_UID or SUDO_UID
FALLBACK_GID = RUNNING_AS_GID or SUDO_GID
try:
    ARCHIVEBOX_ACCOUNT = pwd.getpwnam("archivebox")
except KeyError:
    ARCHIVEBOX_ACCOUNT = None

if DATA_DIR_UID != 0:
    ARCHIVEBOX_USER = DATA_DIR_UID
    ARCHIVEBOX_GROUP = DATA_DIR_GID
elif RUNNING_AS_UID == 0 and ARCHIVEBOX_ACCOUNT is not None:
    ARCHIVEBOX_USER = ARCHIVEBOX_ACCOUNT.pw_uid
    ARCHIVEBOX_GROUP = ARCHIVEBOX_ACCOUNT.pw_gid
else:
    ARCHIVEBOX_USER = EUID or RUNNING_AS_UID or FALLBACK_UID
    ARCHIVEBOX_GROUP = EGID or RUNNING_AS_GID or FALLBACK_GID
if not USER:
    try:
        # alternative method 1 to get username
        USER = pwd.getpwuid(ARCHIVEBOX_USER).pw_name
    except Exception:
        pass

if not USER:
    try:
        # alternative method 2 to get username
        import getpass

        USER = getpass.getuser()
    except Exception:
        pass

if not USER:
    try:
        # alternative method 3 to get username
        USER = os.getlogin() or "archivebox"
    except Exception:
        USER = "archivebox"

ARCHIVEBOX_USER_EXISTS = False
try:
    pwd.getpwuid(ARCHIVEBOX_USER)
    ARCHIVEBOX_USER_EXISTS = True
except Exception:
    ARCHIVEBOX_USER_EXISTS = False


#############################################################################################


def drop_privileges():
    """If running as root, drop privileges to the data dir owner or archivebox user."""

    # Always run ArchiveBox as the user that owns the data dir, or as the
    # archivebox service account when the data dir is root-owned.
    if os.getuid() == 0:
        if os.geteuid() != ARCHIVEBOX_USER and ARCHIVEBOX_USER != 0 and ARCHIVEBOX_USER_EXISTS:
            os.seteuid(ARCHIVEBOX_USER)

            # update environment variables so that subprocesses dont try to write to /root
            pw_record = pwd.getpwuid(ARCHIVEBOX_USER)
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

            try:
                from abxbus import retry as abxbus_retry
            except Exception:
                pass
            else:
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
