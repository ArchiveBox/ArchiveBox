__package__ = 'archivebox.config'

import os
import hashlib
import platform
from pathlib import Path
from functools import cache
from datetime import datetime

from .permissions import SudoPermission, IS_ROOT, ARCHIVEBOX_USER

#############################################################################################

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent    # archivebox source code dir
DATA_DIR: Path = Path(os.getcwd()).resolve()                  # archivebox user data dir
ARCHIVE_DIR: Path = DATA_DIR / 'archive'                      # archivebox snapshot data dir

IN_DOCKER = os.environ.get('IN_DOCKER', False) in ('1', 'true', 'True', 'TRUE', 'yes')

DATABASE_FILE = DATA_DIR / 'index.sqlite3'

#############################################################################################

@cache
def get_collection_id(DATA_DIR=DATA_DIR) -> str:
    """Get a short, stable, unique ID for the current collection (e.g. abc45678)"""
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
        if os.path.isfile(DATABASE_FILE) and os.access(DATA_DIR, os.W_OK):
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


def dir_is_writable(dir_path: Path, uid: int | None = None, gid: int | None = None, fallback=True) -> bool:
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
        pass
        
    return False



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

