from pathlib import Path

from archivebox.config import CONSTANTS

DATA_DIR = CONSTANTS.DATA_DIR
LOGS_DIR = CONSTANTS.LOGS_DIR
TMP_DIR = CONSTANTS.TMP_DIR

Path.mkdir(TMP_DIR, exist_ok=True)
SUPERVISORD_CONFIG_FILE = TMP_DIR / "supervisord.conf"
PID_FILE = TMP_DIR / "supervisord.pid"
SOCK_FILE = TMP_DIR / "supervisord.sock"
LOG_FILE = TMP_DIR / "supervisord.log"
WORKERS_DIR = TMP_DIR / "workers"
