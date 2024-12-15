__package__ = 'archivebox.config'

import os
import socket
import hashlib
import tempfile
import platform
from pathlib import Path
from functools import cache
from datetime import datetime

from benedict import benedict

from .permissions import SudoPermission, IS_ROOT, ARCHIVEBOX_USER

#############################################################################################

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent    # archivebox source code dir
DATA_DIR: Path = Path(os.getcwd()).resolve()                  # archivebox user data dir
ARCHIVE_DIR: Path = DATA_DIR / 'archive'                      # archivebox snapshot data dir

IN_DOCKER = os.environ.get('IN_DOCKER', False) in ('1', 'true', 'True', 'TRUE', 'yes')

DATABASE_FILE = DATA_DIR / 'index.sqlite3'

#############################################################################################

def _get_collection_id(DATA_DIR=DATA_DIR, force_create=False) -> str:
    collection_id_file = DATA_DIR / '.archivebox_id'
    
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
    collection_id = hashlib.sha256(f'{machine_id}:{collection_path}@{creation_date}'.encode()).hexdigest()[:8]
    
    try:
        # only persist collection_id file if we already have an index.sqlite3 file present
        # otherwise we might be running in a directory that is not a collection, no point creating cruft files
        collection_is_active = os.path.isfile(DATABASE_FILE) and os.path.isdir(ARCHIVE_DIR) and os.access(DATA_DIR, os.W_OK)
        if collection_is_active or force_create:
            collection_id_file.write_text(collection_id)
            
            # if we're running as root right now, make sure the collection_id file is owned by the archivebox user
            if IS_ROOT:
                with SudoPermission(uid=0):
                    if ARCHIVEBOX_USER == 0:
                        os.system(f'chmod 777 "{collection_id_file}"')
                    else:    
                        os.system(f'chown {ARCHIVEBOX_USER} "{collection_id_file}"')
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
    
    MACHINE_ID = 'unknown'
    try:
        import machineid
        MACHINE_ID = machineid.hashed_id('archivebox')[:8]
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
    
    OS: str                             = platform.system().lower()    # darwin, linux, etc.
    ARCH: str                           = platform.machine().lower()   # arm64, x86_64, aarch64, etc.
    LIB_DIR_SCOPE: str                  = f'{ARCH}-{OS}-docker' if IN_DOCKER else f'{ARCH}-{OS}'
    return LIB_DIR_SCOPE


def dir_is_writable(dir_path: Path, uid: int | None = None, gid: int | None = None, fallback=True, chown=True) -> bool:
    """Check if a given directory is writable by a specific user and group (fallback=try as current user is unable to check with provided uid)"""
    current_uid, current_gid = os.geteuid(), os.getegid()
    uid, gid = uid or current_uid, gid or current_gid

    test_file = dir_path / '.permissions_test'
    try:
        with SudoPermission(uid=uid, fallback=fallback):
            test_file.exists()
            test_file.write_text(f'Checking if PUID={uid} PGID={gid} can write to dir')
            test_file.unlink()
            return True
    except (IOError, OSError, PermissionError):
        if chown:    
            # try fixing it using sudo permissions
            with SudoPermission(uid=uid, fallback=fallback):
                os.system(f'chown {uid}:{gid} "{dir_path}" 2>/dev/null')
            return dir_is_writable(dir_path, uid=uid, gid=gid, fallback=fallback, chown=False)
    return False

def assert_dir_can_contain_unix_sockets(dir_path: Path) -> bool:
    """Check if a given directory can contain unix sockets (e.g. /tmp/supervisord.sock)"""
    from archivebox.misc.logging_util import pretty_path
    
    try:
        socket_path = str(dir_path / '.test_socket.sock')
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
        raise Exception(f'ArchiveBox failed to create a test UNIX socket file in {pretty_path(dir_path, color=False)}') from e
    
    return True


def create_and_chown_dir(dir_path: Path) -> None:
    with SudoPermission(uid=0, fallback=True):
        dir_path.mkdir(parents=True, exist_ok=True)
        os.system(f'chown {ARCHIVEBOX_USER} "{dir_path}" 2>/dev/null')
        os.system(f'chown {ARCHIVEBOX_USER} "{dir_path}"/* 2>/dev/null &')

@cache
def get_or_create_working_tmp_dir(autofix=True, quiet=True):
    from archivebox import CONSTANTS
    from archivebox.config.common import STORAGE_CONFIG
    from archivebox.misc.checks import check_tmp_dir

    # try a few potential directories in order of preference
    CANDIDATES = [
        STORAGE_CONFIG.TMP_DIR,                                                # <user-specified>
        CONSTANTS.DEFAULT_TMP_DIR,                                             # ./data/tmp/<machine_id>
        Path('/var/run/archivebox') / get_collection_id(),                     # /var/run/archivebox/abc5d8512
        Path('/tmp') / 'archivebox' / get_collection_id(),                     # /tmp/archivebox/abc5d8512
        Path('~/.tmp/archivebox').expanduser() / get_collection_id(),          # ~/.tmp/archivebox/abc5d8512
        Path(tempfile.gettempdir()) / 'archivebox' / get_collection_id(),      # /var/folders/qy/6tpfrpx100j1t4l312nz683m0000gn/T/archivebox/abc5d8512
        Path(tempfile.gettempdir()) / 'archivebox' / get_collection_id()[:4],  # /var/folders/qy/6tpfrpx100j1t4l312nz683m0000gn/T/archivebox/abc5d
        Path(tempfile.gettempdir()) / 'abx' / get_collection_id()[:4],         # /var/folders/qy/6tpfrpx100j1t4l312nz683m0000gn/T/abx/abc5
    ]
    for candidate in CANDIDATES:
        try:
            create_and_chown_dir(candidate)
        except Exception:
            pass
        if check_tmp_dir(candidate, throw=False, quiet=True, must_exist=True):
            if autofix and STORAGE_CONFIG.TMP_DIR != candidate:
                STORAGE_CONFIG.update_in_place(TMP_DIR=candidate)
            return candidate
    
    if not quiet:
        raise OSError(f'ArchiveBox is unable to find a writable TMP_DIR, tried {CANDIDATES}!')

@cache
def get_or_create_working_lib_dir(autofix=True, quiet=False):
    from archivebox import CONSTANTS
    from archivebox.config.common import STORAGE_CONFIG
    from archivebox.misc.checks import check_lib_dir
    
    # try a few potential directories in order of preference
    CANDIDATES = [
        STORAGE_CONFIG.LIB_DIR,                                                   # <user-specified>
        CONSTANTS.DEFAULT_LIB_DIR,                                                # ./data/lib/arm64-linux-docker
        Path('/usr/local/share/archivebox') / get_collection_id(),                # /usr/local/share/archivebox/abc5
        *([Path('/opt/homebrew/share/archivebox') / get_collection_id()] if os.path.isfile('/opt/homebrew/bin/archivebox') else []),  # /opt/homebrew/share/archivebox/abc5
        Path('~/.local/share/archivebox').expanduser() / get_collection_id(),     # ~/.local/share/archivebox/abc5
    ]
    
    for candidate in CANDIDATES:
        try:
            create_and_chown_dir(candidate)
        except Exception:
            pass
        if check_lib_dir(candidate, throw=False, quiet=True, must_exist=True):
            if autofix and STORAGE_CONFIG.LIB_DIR != candidate:
                STORAGE_CONFIG.update_in_place(LIB_DIR=candidate)
            return candidate
    
    if not quiet:
        raise OSError(f'ArchiveBox is unable to find a writable LIB_DIR, tried {CANDIDATES}!')



@cache
def get_data_locations():
    from archivebox.config import CONSTANTS
    from archivebox.config.common import STORAGE_CONFIG
    
    return benedict({
        "DATA_DIR": {
            "path": DATA_DIR.resolve(),
            "enabled": True,
            "is_valid": os.path.isdir(DATA_DIR) and os.access(DATA_DIR, os.R_OK) and os.access(DATA_DIR, os.W_OK),
            "is_mount": os.path.ismount(DATA_DIR.resolve()),
        },
        "CONFIG_FILE": {
            "path": CONSTANTS.CONFIG_FILE.resolve(),
            "enabled": True,
            "is_valid": os.path.isfile(CONSTANTS.CONFIG_FILE) and os.access(CONSTANTS.CONFIG_FILE, os.R_OK) and os.access(CONSTANTS.CONFIG_FILE, os.W_OK),
        },
        "SQL_INDEX": {
            "path": DATABASE_FILE.resolve(),
            "enabled": True,
            "is_valid": os.path.isfile(DATABASE_FILE) and os.access(DATABASE_FILE, os.R_OK) and os.access(DATABASE_FILE, os.W_OK),
            "is_mount": os.path.ismount(DATABASE_FILE.resolve()),
        },
        "QUEUE_DATABASE": {
            "path": CONSTANTS.QUEUE_DATABASE_FILE,
            "enabled": True,
            "is_valid": os.path.isfile(CONSTANTS.QUEUE_DATABASE_FILE) and os.access(CONSTANTS.QUEUE_DATABASE_FILE, os.R_OK) and os.access(CONSTANTS.QUEUE_DATABASE_FILE, os.W_OK),
            "is_mount": os.path.ismount(CONSTANTS.QUEUE_DATABASE_FILE),
        },
        "ARCHIVE_DIR": {
            "path": ARCHIVE_DIR.resolve(),
            "enabled": True,
            "is_valid": os.path.isdir(ARCHIVE_DIR) and os.access(ARCHIVE_DIR, os.R_OK) and os.access(ARCHIVE_DIR, os.W_OK),
            "is_mount": os.path.ismount(ARCHIVE_DIR.resolve()),
        },
        "SOURCES_DIR": {
            "path": CONSTANTS.SOURCES_DIR.resolve(),
            "enabled": True,
            "is_valid": os.path.isdir(CONSTANTS.SOURCES_DIR) and os.access(CONSTANTS.SOURCES_DIR, os.R_OK) and os.access(CONSTANTS.SOURCES_DIR, os.W_OK),
        },
        "PERSONAS_DIR": {
            "path": CONSTANTS.PERSONAS_DIR.resolve(),
            "enabled": os.path.isdir(CONSTANTS.PERSONAS_DIR),
            "is_valid": os.path.isdir(CONSTANTS.PERSONAS_DIR) and os.access(CONSTANTS.PERSONAS_DIR, os.R_OK) and os.access(CONSTANTS.PERSONAS_DIR, os.W_OK),                 # read + write
        },
        "LOGS_DIR": {
            "path": CONSTANTS.LOGS_DIR.resolve(),
            "enabled": True,
            "is_valid": os.path.isdir(CONSTANTS.LOGS_DIR) and os.access(CONSTANTS.LOGS_DIR, os.R_OK) and os.access(CONSTANTS.LOGS_DIR, os.W_OK),                             # read + write
        },
        'TMP_DIR': {
            'path': STORAGE_CONFIG.TMP_DIR.resolve(),
            'enabled': True,
            'is_valid': os.path.isdir(STORAGE_CONFIG.TMP_DIR) and os.access(STORAGE_CONFIG.TMP_DIR, os.R_OK) and os.access(STORAGE_CONFIG.TMP_DIR, os.W_OK),        # read + write
        },
        # "CACHE_DIR": {
        #     "path": CACHE_DIR.resolve(),
        #     "enabled": True,
        #     "is_valid": os.access(CACHE_DIR, os.R_OK) and os.access(CACHE_DIR, os.W_OK),                        # read + write
        # },
    })

@cache
def get_code_locations():
    from archivebox.config import CONSTANTS
    from archivebox.config.common import STORAGE_CONFIG
    
    return benedict({
        'PACKAGE_DIR': {
            'path': (PACKAGE_DIR).resolve(),
            'enabled': True,
            'is_valid': os.access(PACKAGE_DIR / '__main__.py', os.X_OK),                                                                  # executable
        },
        'TEMPLATES_DIR': {
            'path': CONSTANTS.TEMPLATES_DIR.resolve(),
            'enabled': True,
            'is_valid': os.access(CONSTANTS.STATIC_DIR, os.R_OK) and os.access(CONSTANTS.STATIC_DIR, os.X_OK),                                                # read + list
        },
        'CUSTOM_TEMPLATES_DIR': {
            'path': CONSTANTS.CUSTOM_TEMPLATES_DIR.resolve(),
            'enabled': os.path.isdir(CONSTANTS.CUSTOM_TEMPLATES_DIR),
            'is_valid': os.path.isdir(CONSTANTS.CUSTOM_TEMPLATES_DIR) and os.access(CONSTANTS.CUSTOM_TEMPLATES_DIR, os.R_OK),                                      # read
        },
        'USER_PLUGINS_DIR': {
            'path': CONSTANTS.USER_PLUGINS_DIR.resolve(),
            'enabled': os.path.isdir(CONSTANTS.USER_PLUGINS_DIR),
            'is_valid': os.path.isdir(CONSTANTS.USER_PLUGINS_DIR) and os.access(CONSTANTS.USER_PLUGINS_DIR, os.R_OK),                                              # read
        },
        'LIB_DIR': {
            'path': STORAGE_CONFIG.LIB_DIR.resolve(),
            'enabled': True,
            'is_valid': os.path.isdir(STORAGE_CONFIG.LIB_DIR) and os.access(STORAGE_CONFIG.LIB_DIR, os.R_OK) and os.access(STORAGE_CONFIG.LIB_DIR, os.W_OK),                      # read + write
        },
    })



# @cache
# def get_LIB_DIR():
#     """
#     - should be shared with other collections on the same host
#     - must be scoped by CPU architecture, OS family, and archivebox version
#     - should not be shared with other hosts/archivebox versions
#     - must be writable by any archivebox user
#     - should be persistent across reboots
#     - can be on a docker bin mount but probably shouldnt be
#     - ok to have a long path (doesnt contain SOCKETS)
#     """
#     from .version import detect_installed_version
    
#     HOST_DIRS = PlatformDirs(appname='archivebox', appauthor='ArchiveBox', version=detect_installed_version(), opinion=True, ensure_exists=False)
    
#     lib_dir = tempfile.gettempdir()
#     try:
#         if 'SYSTEM_LIB_DIR' in os.environ:
#             lib_dir = Path(os.environ['SYSTEM_LIB_DIR'])
#         else:
#             with SudoPermission(uid=ARCHIVEBOX_USER, fallback=True):
#                 lib_dir = HOST_DIRS.site_data_path
        
#         # Docker: /usr/local/share/archivebox/0.8.5
#         # Ubuntu: /usr/local/share/archivebox/0.8.5
#         # macOS: /Library/Application Support/archivebox
#         try:
#             with SudoPermission(uid=0, fallback=True):
#                 lib_dir.mkdir(parents=True, exist_ok=True)
#         except PermissionError:
#             # our user cannot 
#             lib_dir = HOST_DIRS.user_data_path
#             lib_dir.mkdir(parents=True, exist_ok=True)
        
#         if IS_ROOT or not dir_is_writable(lib_dir, uid=ARCHIVEBOX_USER):
#             if IS_ROOT:
#                 # make sure lib dir is owned by the archivebox user, not root
#                 with SudoPermission(uid=0):
#                     if ARCHIVEBOX_USER == 0:
#                         # print(f'[yellow]:warning:  Waring: Creating SYSTEM_LIB_DIR {lib_dir} with mode 777 so that non-root archivebox users can share it.[/yellow] (caches shared libs used by archivebox for performance)', file=sys.stderr)
#                         os.system(f'chmod -R 777 "{lib_dir}"')
#                     else:
#                         os.system(f'chown {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP} "{lib_dir}"')
#             else:
#                 raise PermissionError()
#     except (PermissionError, AssertionError):
#         # raise PermissionError(f'SYSTEM_LIB_DIR {lib_dir} is not writable by archivebox user {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}')
#         print(f'[red]:cross_mark:  ERROR: SYSTEM_LIB_DIR {lib_dir} is not writable by archivebox user {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}[/red]', file=sys.stderr)
        
#     return lib_dir
    
# @cache
# def get_TMP_DIR():
#     """
#     - must NOT be inside DATA_DIR / inside a docker volume bind mount
#     - must NOT have a long PATH (UNIX socket path length restrictions)
#     - must NOT be shared with other collections/hosts
#     - must be writable by archivebox user & root
#     - must be cleared on every boot / not persisted
#     - must be cleared on every archivebox version upgrade
#     """
#     from .version import detect_installed_version
    
#     HOST_DIRS = PlatformDirs(appname='archivebox', appauthor='ArchiveBox', version=detect_installed_version(), opinion=True, ensure_exists=False)
    
#     # print('DATA_DIR OWNED BY:', ARCHIVEBOX_USER, ARCHIVEBOX_GROUP)
#     # print('RUNNING AS:', self.PUID, self.PGID)
#     run_dir = tempfile.gettempdir()
#     try:
#         if 'SYSTEM_TMP_DIR' in os.environ:
#             run_dir = Path(os.environ['SYSTEM_TMP_DIR']).resolve() / get_collection_id(DATA_DIR=DATA_DIR)
#             with SudoPermission(uid=0, fallback=True):
#                 run_dir.mkdir(parents=True, exist_ok=True)
#             if not dir_is_writable(run_dir, uid=ARCHIVEBOX_USER):
#                 if IS_ROOT:
#                     with SudoPermission(uid=0, fallback=False):
#                         if ARCHIVEBOX_USER == 0:
#                             # print(f'[yellow]:warning:  Waring: Creating SYSTEM_TMP_DIR {run_dir} with mode 777 so that non-root archivebox users can access it.[/yellow]', file=sys.stderr)
#                             os.system(f'chmod -R 777 "{run_dir}"')
#                         else:
#                             os.system(f'chown {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP} "{run_dir}"')
#                 else:
#                     raise PermissionError()
#             assert len(str(run_dir / 'supervisord.conf')) < 95, 'SYSTEM_TMP_DIR path is too long, please set SYSTEM_TMP_DIR env variable to a shorter path (unfortunately unix requires socket paths be < 108 chars)'
#             return run_dir
        
#         run_dir = (HOST_DIRS.site_runtime_path / get_collection_id(DATA_DIR=DATA_DIR)).resolve()
#         try:
#             assert len(str(run_dir)) + len('/supervisord.sock') < 95
#         except AssertionError:
#             run_dir = Path(tempfile.gettempdir()).resolve() / 'archivebox' / get_collection_id(DATA_DIR=DATA_DIR)
#             assert len(str(run_dir)) + len('/supervisord.sock') < 95, 'SYSTEM_TMP_DIR path is too long, please set SYSTEM_TMP_DIR env variable to a shorter path (unfortunately unix requires socket paths be < 108 chars)'
        
#         with SudoPermission(uid=0, fallback=True):
#             run_dir.mkdir(parents=True, exist_ok=True)
            
#         if IS_ROOT or not dir_is_writable(run_dir, uid=ARCHIVEBOX_USER):
#             if IS_ROOT:
#                 with SudoPermission(uid=0):
#                     if ARCHIVEBOX_USER == 0:
#                         # print(f'[yellow]:warning:  Waring: Creating SYSTEM_TMP_DIR {run_dir} with mode 777 so that non-root archivebox users can access it.[/yellow]', file=sys.stderr)
#                         os.system(f'chmod -R 777 "{run_dir}"')
#                     else:
#                         os.system(f'chown {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP} "{run_dir}"')
#             else:
#                 raise PermissionError()
            
#     except (PermissionError, AssertionError):
#         # raise PermissionError(f'SYSTEM_TMP_DIR {run_dir} is not writable by archivebox user {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}')
#         print(f'[red]:cross_mark:  ERROR: SYSTEM_TMP_DIR {run_dir} is not writable by archivebox user {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}[/red]', file=sys.stderr)
        
#     return run_dir

