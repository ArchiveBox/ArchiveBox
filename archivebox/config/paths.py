__package__ = 'archivebox.config'

import os
import tempfile
import hashlib
from pathlib import Path

from functools import cache
from platformdirs import PlatformDirs

from .permissions import SudoPermission, IS_ROOT, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP

#############################################################################################

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent    # archivebox source code dir
DATA_DIR: Path = Path(os.getcwd()).resolve()                  # archivebox user data dir
ARCHIVE_DIR: Path = DATA_DIR / 'archive'                      # archivebox snapshot data dir

#############################################################################################

@cache
def get_collection_id(DATA_DIR=DATA_DIR):
    """Get a short, stable, unique ID for the current collection"""
    collection_id_file = DATA_DIR / '.collection_id'
    
    try:
        return collection_id_file.read_text().strip()
    except (OSError, FileNotFoundError, PermissionError):
        pass
    
    hash_key = str(DATA_DIR.resolve()).encode()
    collection_id = hashlib.sha256(hash_key).hexdigest()[:8]
    try:
        collection_id_file.write_text(collection_id)
    except (OSError, FileNotFoundError, PermissionError):
        pass
    return collection_id


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



@cache
def get_LIB_DIR():
    """
    - should be shared with other collections on the same host
    - must be scoped by CPU architecture, OS family, and archivebox version
    - should not be shared with other hosts/archivebox versions
    - must be writable by any archivebox user
    - should be persistent across reboots
    - can be on a docker bin mount but probably shouldnt be
    - ok to have a long path (doesnt contain SOCKETS)
    """
    from .version import detect_installed_version
    
    HOST_DIRS = PlatformDirs(appname='archivebox', appauthor='ArchiveBox', version=detect_installed_version(), opinion=True, ensure_exists=False)
    
    if 'SYSTEM_LIB_DIR' in os.environ:
        lib_dir = Path(os.environ['SYSTEM_LIB_DIR'])
    else:
        with SudoPermission(uid=ARCHIVEBOX_USER, fallback=True):
            lib_dir = HOST_DIRS.site_data_path
    
    # Docker: /usr/local/share/archivebox/0.8.5
    # Ubuntu: /usr/local/share/archivebox/0.8.5
    # macOS: /Library/Application Support/archivebox
    try:
        with SudoPermission(uid=0, fallback=True):
            lib_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # our user cannot 
        lib_dir = HOST_DIRS.user_data_path
        lib_dir.mkdir(parents=True, exist_ok=True)
    
    if not dir_is_writable(lib_dir):
        if IS_ROOT:
            # make sure lib dir is owned by the archivebox user, not root
            with SudoPermission(uid=0):
                os.system(f'chown {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP} "{lib_dir}"')
        else:
            raise PermissionError(f'SYSTEM_LIB_DIR {lib_dir} is not writable by archivebox user {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}')
        
    return lib_dir
    
@cache
def get_TMP_DIR():
    """
    - must NOT be inside DATA_DIR / inside a docker volume bind mount
    - must NOT have a long PATH (UNIX socket path length restrictions)
    - must NOT be shared with other collections/hosts
    - must be writable by archivebox user & root
    - must be cleared on every boot / not persisted
    - must be cleared on every archivebox version upgrade
    """
    from .version import detect_installed_version
    
    HOST_DIRS = PlatformDirs(appname='archivebox', appauthor='ArchiveBox', version=detect_installed_version(), opinion=True, ensure_exists=False)
    
    # print('DATA_DIR OWNED BY:', ARCHIVEBOX_USER, ARCHIVEBOX_GROUP)
    # print('RUNNING AS:', self.PUID, self.PGID)
    
    if 'SYSTEM_TMP_DIR' in os.environ:
        run_dir = Path(os.environ['SYSTEM_TMP_DIR']).resolve() / get_collection_id(DATA_DIR=DATA_DIR)
        with SudoPermission(uid=0, fallback=True):
            run_dir.mkdir(parents=True, exist_ok=True)
        if not dir_is_writable(run_dir):
            if IS_ROOT:
                with SudoPermission(uid=0, fallback=False):
                    os.system(f'chown {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP} "{run_dir}"')
            else:
                raise PermissionError(f'SYSTEM_TMP_DIR {run_dir} is not writable by archivebox user {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}')
        assert len(str(run_dir / 'supervisord.conf')) < 95, 'SYSTEM_TMP_DIR path is too long, please set SYSTEM_TMP_DIR env variable to a shorter path (unfortunately unix requires socket paths be < 108 chars)'
        return run_dir
    
    run_dir = (HOST_DIRS.site_runtime_path / get_collection_id(DATA_DIR=DATA_DIR)).resolve()
    try:
        assert len(str(run_dir)) + len('/supervisord.sock') < 95
    except AssertionError:
        run_dir = Path(tempfile.gettempdir()).resolve() / 'archivebox' / get_collection_id(DATA_DIR=DATA_DIR)
        assert len(str(run_dir)) + len('/supervisord.sock') < 95, 'SYSTEM_TMP_DIR path is too long, please set SYSTEM_TMP_DIR env variable to a shorter path (unfortunately unix requires socket paths be < 108 chars)'
    
    with SudoPermission(uid=0, fallback=True):
        run_dir.mkdir(parents=True, exist_ok=True)
        
    if not dir_is_writable(run_dir):
        if IS_ROOT:
            with SudoPermission(uid=0):
                os.system(f'chown {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP} "{run_dir}"')
        else:
            raise PermissionError(f'SYSTEM_TMP_DIR {run_dir} is not writable by archivebox user {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}')
    
    # Docker: /tmp/archivebox/0.8.5/abc324235
    # Ubuntu: /tmp/archivebox/0.8.5/abc324235
    # macOS: /var/folders/qy/6tpfrpx100j1t4l312nz683m0000gn/T/archivebox/0.8.5/abc324235
    return run_dir

