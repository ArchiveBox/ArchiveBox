import tempfile
from pathlib import Path

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


def get_sock_file():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    
    if len(str(SOCK_FILE)) > 100:
        # socket absolute paths cannot be longer than 108 characters on some systems
        # symlink it to a shorter path and use that instead
        
        # use tmpfile to atomically overwrite any existing symlink
        symlink = Path(tempfile.gettempdir()) / f"archivebox_supervisord_{get_collection_id()}.sock.tmp"
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(SOCK_FILE)
        symlink.rename(str(symlink).replace('.sock.tmp', '.sock'))
        assert len(str(symlink)) <= 100, f'Failed to create supervisord SOCK_FILE, system tmp dir location is too long {symlink} (unix only allows 108 characters for socket paths)'
        return symlink
        
    return SOCK_FILE
