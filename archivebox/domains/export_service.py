"""Site export jobs use the existing Process lifecycle and logs."""

import json
import hashlib
import sys
from pathlib import Path

from archivebox.config import CONSTANTS
from archivebox.machine.models import Machine, Process
from .scope import normalize_site_scope, crawl_site_scope

FORMATS = {"html_zip": "Static HTML ZIP", "html": "Static HTML", "wacz": "WACZ", "replay": "WACZ + ReplayWeb.page"}


def export_log_prefix(scope):
    key = hashlib.sha256(normalize_site_scope(scope).encode()).hexdigest()
    return str(CONSTANTS.DATA_DIR / "logs" / "site-exports" / key) + "/"


def launch_export(crawl=None, *, scope=None, directory, format, max_bytes=None):
    scope = normalize_site_scope(scope or crawl_site_scope(crawl))
    if format not in FORMATS:
        raise ValueError("Select an export format.")
    parent = Path(directory)
    if not parent.is_absolute():
        raise ValueError("Enter an absolute server directory path.")
    parent = parent.resolve()
    process = Process(machine=Machine.current(), process_type=Process.TypeChoices.CLI, worker_type="site-export", timeout=0)
    destination = parent / f"site-{process.pk}"
    logs = Path(export_log_prefix(scope)) / str(process.pk)
    process.pwd = str(logs)
    process.cmd = [
        sys.executable,
        "-m",
        "archivebox",
        "manage",
        "site_export",
        "--scope",
        scope,
        "--format",
        format,
        "--destination",
        str(destination),
        "--process-id",
        str(process.pk),
    ]
    if max_bytes is not None:
        process.cmd.extend(["--max-bytes", str(int(max_bytes))])
    process.save()
    return process.launch(background=True, cwd=str(CONSTANTS.DATA_DIR))


def export_jobs(crawl=None, *, scope=None):
    prefix = export_log_prefix(scope or crawl_site_scope(crawl))
    jobs = list(Process.objects.filter(worker_type="site-export", pwd__startswith=prefix).order_by("-created_at")[:10])
    for process in jobs:
        process.poll()
        process.export_report = {}
        path = process.stdout_file
        if path and path.is_file():
            # Progress is one bounded JSON line, even for multi-day exports.
            with path.open("rb") as source:
                source.seek(max(0, path.stat().st_size - 65536))
                for line in source.read().splitlines():
                    try:
                        entry = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(entry, dict) and "destination" in entry:
                        process.export_report = entry
        if not process.export_report and "--destination" in process.cmd:
            process.export_report = {"destination": process.cmd[process.cmd.index("--destination") + 1]}
    return jobs
