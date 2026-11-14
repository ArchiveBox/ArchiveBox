"""Site export jobs use the existing Process lifecycle and logs."""

import json
import hashlib
import sys
from pathlib import Path

from archivebox.config import CONSTANTS
from archivebox.machine.models import Machine, Process
from django.utils import timezone
from .scope import crawl_site_scope, site_snapshot_filters

FORMATS = {"html_zip": "Static HTML ZIP", "html": "Static HTML to Disk", "wacz": "WACZ"}


def export_log_prefix(scope=None, *, query=None, user=None, public_only=False):
    from archivebox.core.exports import normalize_export_query

    query = normalize_export_query(query if query is not None else site_snapshot_filters(scope))
    principal = str(user.pk) if user is not None and user.is_authenticated else None
    selection = [sorted(query.lists()), principal, bool(public_only)]
    key = hashlib.sha256(json.dumps(selection, separators=(",", ":")).encode()).hexdigest()
    return str(CONSTANTS.DATA_DIR / "logs" / "site-exports" / key) + "/"


def launch_export(crawl=None, *, scope=None, query=None, user=None, public_only=False, directory, format, max_bytes=None):
    from archivebox.core.exports import MAX_ARCHIVE_BYTES, normalize_export_query

    if query is not None and (scope or crawl is not None):
        raise ValueError("Select a snapshot query or a domain scope, not both.")
    query = normalize_export_query(query if query is not None else site_snapshot_filters(scope or crawl_site_scope(crawl)))
    if format not in FORMATS:
        raise ValueError("Select an export format.")
    format = next(value for value in FORMATS if value == format)
    if format in {"html_zip", "wacz"}:
        max_bytes = min(max_bytes, MAX_ARCHIVE_BYTES) if max_bytes and max_bytes > 0 else MAX_ARCHIVE_BYTES
    parent = Path(directory)
    if not parent.is_absolute():
        raise ValueError("Enter an absolute server directory path.")
    parent = parent.resolve()
    process = Process(machine=Machine.current(), process_type=Process.TypeChoices.CLI, worker_type="site-export", timeout=0)
    destination = parent / f"site-{process.pk}"
    logs = Path(export_log_prefix(query=query, user=user, public_only=public_only)) / str(process.pk)
    process.pwd = str(logs)
    process.cmd = [
        sys.executable,
        "-m",
        "archivebox",
        "manage",
        "site_export",
        "--query",
        query.urlencode(),
        "--before",
        timezone.now().isoformat(),
        "--format",
        format,
        "--destination",
        str(destination),
        "--process-id",
        str(process.pk),
    ]
    if user is not None and user.is_authenticated:
        process.cmd.extend(["--user", str(user.pk)])
    if public_only:
        process.cmd.append("--public-only")
    if max_bytes is not None:
        process.cmd.extend(["--max-bytes", str(int(max_bytes))])
    process.save()
    return process.launch(background=True, cwd=str(CONSTANTS.DATA_DIR))


def export_jobs(crawl=None, *, scope=None, query=None, user=None, public_only=False, process_id=None):
    query = query if query is not None else site_snapshot_filters(scope or crawl_site_scope(crawl))
    prefix = export_log_prefix(query=query, user=user, public_only=public_only)
    selected = Process.objects.filter(worker_type="site-export", pwd__startswith=prefix).order_by("-created_at")
    jobs = list(selected.filter(pk=process_id) if process_id is not None else selected[:10])
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
        format = process.cmd[process.cmd.index("--format") + 1]
        process.export_label = FORMATS.get(format, format)
    return jobs
