import tempfile
from pathlib import Path
from functools import cache

from archivebox.config import CONSTANTS
from archivebox.config.paths import get_collection_id

DATA_DIR = CONSTANTS.DATA_DIR
LOGS_DIR = CONSTANTS.LOGS_DIR
TMP_DIR = CONSTANTS.TMP_DIR

SUPERVISORD_CONFIG_FILE = TMP_DIR / "supervisord.conf"
PID_FILE = TMP_DIR / "supervisord.pid"
SOCK_FILE = TMP_DIR / "supervisord.sock"
LOG_FILE = TMP_DIR / "supervisord.log"
WORKERS_DIR = TMP_DIR / "workers"

@cache
def get_sock_file():
    """Get the path to the supervisord socket file, symlinking to a shorter path if needed due to unix path length limits"""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    
    if len(f'file://{SOCK_FILE.absolute().resolve()}') > 98:
        # socket absolute paths cannot be longer than 104 bytes on macos, and 108 bytes on linux
        # symlink it to a shorter path and use that instead
        
        # place the actual socket file in a shorter tmp dir
        # /var/folders/qy/6tpfrpx100j1t4l312nz683m0000gn/T/archivebox_supervisord_3d1e544e.sock
        shorter_sock_file = Path(tempfile.gettempdir()) / f"archivebox_supervisord_{get_collection_id()}.sock"
        
        # symlink ./data/tmp/<collection_id>/supervisord.sock -> /var/folders/qy/abc234235/T/archivebox_supervisord_3d1e544e.sock
        # for convenience/consistency
        symlink = SOCK_FILE
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(shorter_sock_file)
        
        assert len(f'file://{shorter_sock_file}') <= 98, f'Failed to create supervisord SOCK_FILE, system tmp dir location is too long {shorter_sock_file} (unix only allows 108 characters for socket paths)'
        return shorter_sock_file
        
    return SOCK_FILE
