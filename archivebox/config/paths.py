__package__ = "archivebox.config"

import os
import socket
import hashlib
import tempfile
import platform
from pathlib import Path
from functools import cache
from datetime import datetime
from typing import TYPE_CHECKING

from .permissions import SudoPermission, IS_ROOT, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP

if TYPE_CHECKING:
    from archivebox.config.common import ArchiveBoxConfig

#############################################################################################

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent  # archivebox source code dir
DATA_DIR: Path = Path(os.getcwd()).resolve()  # archivebox user data dir
MAX_TMP_SOCKET_URL_LENGTH = 90
SUPERVISORD_SOCKET_FILENAME = "supervisord.sock"


def _env_path(key: str, default: Path) -> Path:
    path = Path(os.environ.get(key) or default).expanduser()
    if not path.is_absolute():
        path = DATA_DIR / path
    return path.resolve()


ARCHIVE_DIR: Path = DATA_DIR / "archive"  # archivebox snapshot data dir
USERS_DIR: Path = ARCHIVE_DIR / "users"  # archivebox user-scoped crawl/snapshot data dir

IN_DOCKER = os.environ.get("IN_DOCKER", False) in ("1", "true", "True", "TRUE", "yes")

DATABASE_FILE = DATA_DIR / "index.sqlite3"

#############################################################################################


def _get_collection_id(DATA_DIR=DATA_DIR, force_create=False) -> str:
    collection_id_file = DATA_DIR / ".archivebox_id"

    try:
        return collection_id_file.read_text().strip()
    except (OSError, FileNotFoundError, PermissionError):
        pass

    # hash the machine_id + collection dir path + creation time to get a unique collection_id
    machine_id = get_machine_id()
    collection_path = DATA_DIR.resolve()
    try:
        creation_date = DATA_DIR.stat().st_ctime
    except Exception:
        creation_date = datetime.now().isoformat()
    collection_id = hashlib.sha256(f"{machine_id}:{collection_path}@{creation_date}".encode()).hexdigest()[:8]

    try:
        # only persist collection_id file if this dir already looks like a real collection
        # (has an index.sqlite3, or an ArchiveBox.conf when the DB lives in postgres),
        # otherwise we might be running in a directory that is not a collection, no point creating cruft files
        collection_marker = os.path.isfile(DATABASE_FILE) or os.path.isfile(DATA_DIR / "ArchiveBox.conf")
        collection_is_active = collection_marker and os.path.isdir(ARCHIVE_DIR) and os.access(DATA_DIR, os.W_OK)
        if collection_is_active or force_create:
            collection_id_file.write_text(collection_id)

            # if we're running as root right now, make sure the collection_id file is owned by the archivebox user
            if IS_ROOT:
                with SudoPermission(uid=0):
                    if ARCHIVEBOX_USER == 0:
                        collection_id_file.chmod(0o777)
                    else:
                        os.chown(collection_id_file, ARCHIVEBOX_USER, -1)
    except (OSError, FileNotFoundError, PermissionError):
        pass
    return collection_id


@cache
def get_collection_id(DATA_DIR=DATA_DIR) -> str:
    """Get a short, stable, unique ID for the current collection (e.g. abc45678)"""
    return _get_collection_id(DATA_DIR=DATA_DIR)


@cache
def get_machine_id() -> str:
    """Get a short, stable, unique ID for the current machine (e.g. abc45678)"""

    MACHINE_ID = "unknown"
    try:
        import machineid

        MACHINE_ID = machineid.hashed_id("archivebox")[:8]
    except Exception:
        try:
            import uuid
            import hashlib

            MACHINE_ID = hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:8]
        except Exception:
            pass
    return MACHINE_ID


@cache
def get_machine_type() -> str:
    """Get a short, stable, unique type identifier for the current machine (e.g. linux-x86_64-docker)"""

    OS: str = platform.system().lower()  # darwin, linux, etc.
    ARCH: str = platform.machine().lower()  # arm64, x86_64, aarch64, etc.
    LIB_DIR_SCOPE: str = f"{ARCH}-{OS}-docker" if IN_DOCKER else f"{ARCH}-{OS}"
    return LIB_DIR_SCOPE


def dir_is_writable(dir_path: Path, uid: int | None = None, gid: int | None = None, fallback=True, chown=True) -> bool:
    """Check if a given directory is writable by a specific user and group (fallback=try as current user is unable to check with provided uid)"""
    current_uid, current_gid = os.geteuid(), os.getegid()
    uid, gid = uid or current_uid, gid or current_gid

    test_file = dir_path / ".permissions_test"
    try:
        with SudoPermission(uid=uid, fallback=fallback):
            test_file.exists()
            test_file.write_text(f"Checking if uid={uid} gid={gid} can write to dir")
            test_file.unlink()
            return True
    except (OSError, PermissionError):
        if chown:
            # try fixing it using sudo permissions
            with SudoPermission(uid=uid, fallback=fallback):
                os.chown(dir_path, uid, gid)
            return dir_is_writable(dir_path, uid=uid, gid=gid, fallback=fallback, chown=False)
    return False


def assert_dir_can_contain_unix_sockets(dir_path: Path) -> bool:
    """Check if a given directory can contain unix sockets (e.g. /tmp/supervisord.sock)"""
    from archivebox.misc.logging_util import pretty_path

    try:
        socket_path = str(dir_path / ".test_socket.sock")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            os.remove(socket_path)
        except OSError:
            pass
        s.bind(socket_path)
        s.close()
        try:
            os.remove(socket_path)
        except OSError:
            pass
    except Exception as e:
        raise Exception(f"ArchiveBox failed to create a test UNIX socket file in {pretty_path(dir_path, color=False)}") from e

    return True


def create_and_chown_dir(dir_path: Path) -> None:
    """Create a required runtime dir and fix only that dir's ownership when needed."""
    dir_existed = dir_path.exists()
    dir_path.mkdir(parents=True, exist_ok=True)

    try:
        stat = dir_path.stat()
    except OSError:
        return

    if dir_existed and stat.st_uid == ARCHIVEBOX_USER and stat.st_gid == ARCHIVEBOX_GROUP:
        return

    with SudoPermission(uid=0, fallback=True):
        try:
            os.chown(dir_path, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP)
        except (OSError, PermissionError):
            pass


def tmp_dir_socket_path_is_short_enough(dir_path: Path) -> bool:
    socket_file = dir_path.absolute().resolve() / SUPERVISORD_SOCKET_FILENAME
    return len(f"file://{socket_file}") < MAX_TMP_SOCKET_URL_LENGTH


def tmp_dir_candidates(config: "ArchiveBoxConfig") -> list[Path]:
    from archivebox.config.constants import CONSTANTS

    collection_id = get_collection_id()
    collection_id_short = collection_id[:4]
    system_tmp_dir = Path(tempfile.gettempdir())
    candidates = [
        config.TMP_DIR,  # <user-specified>
        CONSTANTS.DEFAULT_TMP_DIR,  # ./data/tmp/<machine_id>
        Path("/var/run/archivebox") / collection_id,
        Path("/tmp") / "archivebox" / collection_id,
        Path("~/.tmp/archivebox").expanduser() / collection_id,
        system_tmp_dir / "archivebox" / collection_id,
        system_tmp_dir / "archivebox" / collection_id_short,
        system_tmp_dir / "abx" / collection_id_short,
    ]
    seen = set()
    unique_candidates = []
    for path in candidates:
        path_key = str(path.expanduser().absolute())
        if path_key in seen:
            continue
        seen.add(path_key)
        unique_candidates.append(path)
    return unique_candidates


def get_or_create_working_tmp_dir(autofix=True, quiet=True, config: "ArchiveBoxConfig | None" = None, **config_kwargs):
    from archivebox.config.common import get_config
    from archivebox.misc.checks import check_tmp_dir

    config = config or get_config(**config_kwargs)
    candidates = tmp_dir_candidates(config)
    fallback_candidate = None
    for candidate in candidates:
        try:
            create_and_chown_dir(candidate)
        except Exception:
            pass
        if check_tmp_dir(candidate, throw=False, quiet=True, must_exist=True, config=config):
            if autofix and config.TMP_DIR != candidate:
                os.environ["TMP_DIR"] = str(candidate)
            return candidate
        try:
            if (
                fallback_candidate is None
                and candidate.exists()
                and dir_is_writable(candidate)
                and tmp_dir_socket_path_is_short_enough(candidate)
            ):
                fallback_candidate = candidate
        except Exception:
            pass

    # Some sandboxed environments disallow AF_UNIX binds entirely.
    # Fall back to the shortest writable path so read-only CLI commands can still run,
    # and let later permission checks surface the missing socket support if needed.
    if fallback_candidate:
        if autofix and config.TMP_DIR != fallback_candidate:
            os.environ["TMP_DIR"] = str(fallback_candidate)
        return fallback_candidate

    if not quiet:
        raise OSError(f"ArchiveBox is unable to find a writable TMP_DIR, tried {candidates}!")


def get_or_create_working_lib_dir(autofix=True, quiet=False, config: "ArchiveBoxConfig | None" = None, **config_kwargs):
    from archivebox.config.common import get_config
    from archivebox.misc.checks import check_lib_dir

    config = config or get_config(**config_kwargs)

    # ABXPKG_LIB_DIR is either the shared platformdirs default or an explicit env/config override.
    CANDIDATES = [config.ABXPKG_LIB_DIR]

    for candidate in CANDIDATES:
        try:
            create_and_chown_dir(candidate)
        except Exception:
            pass
        if check_lib_dir(candidate, throw=False, quiet=True, must_exist=True, config=config):
            if autofix and config.ABXPKG_LIB_DIR != candidate:
                os.environ["ABXPKG_LIB_DIR"] = str(candidate)
            return candidate

    if not quiet:
        raise OSError(f"ArchiveBox is unable to find a writable ABXPKG_LIB_DIR, tried {CANDIDATES}!")


def _sql_index_location(config: "ArchiveBoxConfig") -> dict:
    from archivebox.misc.db import database_display_location, database_exists, is_postgres

    if is_postgres(config):
        return {
            "path": database_display_location(),
            "enabled": True,
            "is_valid": database_exists(),
            "is_mount": False,
        }
    return {
        "path": DATABASE_FILE.resolve(),
        "enabled": True,
        "is_valid": os.path.isfile(DATABASE_FILE) and os.access(DATABASE_FILE, os.R_OK) and os.access(DATABASE_FILE, os.W_OK),
        "is_mount": os.path.ismount(DATABASE_FILE.resolve()),
    }


def get_data_locations(config: "ArchiveBoxConfig | None" = None, **config_kwargs):
    from archivebox.config.constants import CONSTANTS
    from archivebox.config.common import get_config
    from archivebox.misc.logging import AttrDict

    config = config or get_config(**config_kwargs)
    try:
        tmp_dir = get_or_create_working_tmp_dir(autofix=True, quiet=True, config=config) or config.TMP_DIR
    except Exception:
        tmp_dir = config.TMP_DIR

    return AttrDict(
        {
            "DATA_DIR": {
                "path": DATA_DIR.resolve(),
                "enabled": True,
                "is_valid": os.path.isdir(DATA_DIR) and os.access(DATA_DIR, os.R_OK) and os.access(DATA_DIR, os.W_OK),
                "is_mount": os.path.ismount(DATA_DIR.resolve()),
            },
            "CONFIG_FILE": {
                "path": CONSTANTS.CONFIG_FILE.resolve(),
                "enabled": True,
                "is_valid": os.path.isfile(CONSTANTS.CONFIG_FILE)
                and os.access(CONSTANTS.CONFIG_FILE, os.R_OK)
                and os.access(CONSTANTS.CONFIG_FILE, os.W_OK),
            },
            "SQL_INDEX": _sql_index_location(config),
            "ARCHIVE_DIR": {
                "path": CONSTANTS.ARCHIVE_DIR.resolve(),
                "enabled": True,
                "is_valid": os.path.isdir(CONSTANTS.ARCHIVE_DIR)
                and os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK)
                and os.access(CONSTANTS.ARCHIVE_DIR, os.W_OK),
                "is_mount": os.path.ismount(CONSTANTS.ARCHIVE_DIR.resolve()),
            },
            "USERS_DIR": {
                "path": CONSTANTS.USERS_DIR.resolve(),
                "enabled": os.path.isdir(CONSTANTS.USERS_DIR),
                "is_valid": os.path.isdir(CONSTANTS.USERS_DIR)
                and os.access(CONSTANTS.USERS_DIR, os.R_OK)
                and os.access(CONSTANTS.USERS_DIR, os.W_OK),
                "is_mount": os.path.ismount(CONSTANTS.USERS_DIR.resolve()),
            },
            "SOURCES_DIR": {
                "path": CONSTANTS.SOURCES_DIR.resolve(),
                "enabled": True,
                "is_valid": os.path.isdir(CONSTANTS.SOURCES_DIR)
                and os.access(CONSTANTS.SOURCES_DIR, os.R_OK)
                and os.access(CONSTANTS.SOURCES_DIR, os.W_OK),
            },
            "PERSONAS_DIR": {
                "path": CONSTANTS.PERSONAS_DIR.resolve(),
                "enabled": os.path.isdir(CONSTANTS.PERSONAS_DIR),
                "is_valid": os.path.isdir(CONSTANTS.PERSONAS_DIR)
                and os.access(CONSTANTS.PERSONAS_DIR, os.R_OK)
                and os.access(CONSTANTS.PERSONAS_DIR, os.W_OK),  # read + write
            },
            "LOGS_DIR": {
                "path": CONSTANTS.LOGS_DIR.resolve(),
                "enabled": True,
                "is_valid": os.path.isdir(CONSTANTS.LOGS_DIR)
                and os.access(CONSTANTS.LOGS_DIR, os.R_OK)
                and os.access(CONSTANTS.LOGS_DIR, os.W_OK),  # read + write
            },
            "TMP_DIR": {
                "path": tmp_dir.resolve(),
                "enabled": True,
                "is_valid": os.path.isdir(tmp_dir)
                and os.access(tmp_dir, os.R_OK)
                and os.access(tmp_dir, os.W_OK)
                and tmp_dir_socket_path_is_short_enough(tmp_dir),
            },
        },
    )


def get_code_locations(config: "ArchiveBoxConfig | None" = None, **config_kwargs):
    from archivebox.config.constants import CONSTANTS
    from archivebox.config.common import get_config
    from archivebox.misc.logging import AttrDict

    config = config or get_config(**config_kwargs)
    try:
        lib_dir = get_or_create_working_lib_dir(autofix=True, quiet=True, config=config) or config.ABXPKG_LIB_DIR
    except Exception:
        lib_dir = config.ABXPKG_LIB_DIR

    return AttrDict(
        {
            "PACKAGE_DIR": {
                "path": (PACKAGE_DIR).resolve(),
                "enabled": True,
                "is_valid": os.access(PACKAGE_DIR / "__main__.py", os.X_OK),  # executable
            },
            "TEMPLATES_DIR": {
                "path": CONSTANTS.TEMPLATES_DIR.resolve(),
                "enabled": True,
                "is_valid": os.access(CONSTANTS.STATIC_DIR, os.R_OK) and os.access(CONSTANTS.STATIC_DIR, os.X_OK),  # read + list
            },
            "CUSTOM_TEMPLATES_DIR": {
                "path": CONSTANTS.CUSTOM_TEMPLATES_DIR.resolve(),
                "enabled": os.path.isdir(CONSTANTS.CUSTOM_TEMPLATES_DIR),
                "is_valid": os.path.isdir(CONSTANTS.CUSTOM_TEMPLATES_DIR) and os.access(CONSTANTS.CUSTOM_TEMPLATES_DIR, os.R_OK),  # read
            },
            "USER_PLUGINS_DIR": {
                "path": CONSTANTS.USER_PLUGINS_DIR.resolve(),
                "enabled": os.path.isdir(CONSTANTS.USER_PLUGINS_DIR),
                "is_valid": os.path.isdir(CONSTANTS.USER_PLUGINS_DIR) and os.access(CONSTANTS.USER_PLUGINS_DIR, os.R_OK),  # read
            },
            "ABXPKG_LIB_DIR": {
                "path": lib_dir.resolve(),
                "enabled": True,
                "is_valid": os.path.isdir(lib_dir) and os.access(lib_dir, os.R_OK) and os.access(lib_dir, os.W_OK),  # read + write
            },
        },
    )
