from pathlib import Path

from django.conf import settings


OUTPUT_DIR = settings.CONFIG.OUTPUT_DIR
LOGS_DIR = settings.CONFIG.LOGS_DIR

TMP_DIR = OUTPUT_DIR / "tmp"

Path.mkdir(TMP_DIR, exist_ok=True)


CONFIG_FILE = TMP_DIR / "supervisord.conf"
PID_FILE = TMP_DIR / "supervisord.pid"
SOCK_FILE = TMP_DIR / "supervisord.sock"
LOG_FILE = TMP_DIR / "supervisord.log"
WORKER_DIR = TMP_DIR / "workers"
