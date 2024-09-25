from pathlib import Path


import archivebox
OUTPUT_DIR = archivebox.DATA_DIR
LOGS_DIR = archivebox.CONSTANTS.LOGS_DIR

TMP_DIR = archivebox.CONSTANTS.TMP_DIR

Path.mkdir(TMP_DIR, exist_ok=True)
CONFIG_FILE = TMP_DIR / "supervisord.conf"
PID_FILE = TMP_DIR / "supervisord.pid"
SOCK_FILE = TMP_DIR / "supervisord.sock"
LOG_FILE = TMP_DIR / "supervisord.log"
WORKER_DIR = TMP_DIR / "workers"
