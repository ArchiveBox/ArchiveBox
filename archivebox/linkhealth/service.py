"""Check original URLs using native Process logs and Snapshot tags."""

import json
import sys
from collections import deque
from urllib.parse import urlsplit
from uuid import UUID

import requests
from django.utils import timezone

from archivebox.config import CONSTANTS
from archivebox.core.models import Tag
from archivebox.machine.models import Machine, Process


def check_snapshot(snapshot, session):
    """Only confirmed HTTP absence changes a capture's normal offline tag."""
    result = {"snapshot_id": str(snapshot.pk), "url": snapshot.url, "title": snapshot.title, "checked_at": timezone.now().isoformat()}
    parts = urlsplit(snapshot.url)
    if parts.scheme not in {"http", "https"} or parts.username is not None or parts.password is not None:
        return {**result, "status": "unsupported", "message": "Requires HTTP(S) without embedded credentials."}
    try:
        with session.get(snapshot.url, stream=True, timeout=(10, 20), allow_redirects=True) as response:
            code = response.status_code
            status = "other"
            if 200 <= code < 300:
                status = "reachable"
            elif code in {404, 410}:
                status = "offline"
            elif code in {401, 403, 407, 429}:
                status = "restricted"
            elif code >= 500:
                status = "server_error"
            result.update(status=status, status_code=code, final_url=response.url)
    except requests.RequestException:
        result.update(status="unreachable", message="Connection, TLS, redirect or timeout error; offline state is unconfirmed.")
    if result["status"] == "offline":
        tag, _ = Tag.get_or_create_by_name("offline")
        snapshot.add_tag_ids([tag.pk])
    elif result["status"] == "reachable":
        snapshot.remove_tag_ids(list(Tag.objects.filter(name__iexact="offline").values_list("pk", flat=True)))
    return result


def check_snapshots(snapshots, output):
    total = snapshots.count()
    counts = {}
    checked = 0
    output.write(json.dumps({"total": total, "checked": 0}) + "\n")
    output.flush()
    with requests.Session() as session:
        session.trust_env = False
        session.max_redirects = 10
        session.headers["User-Agent"] = "ArchiveBox broken-link checker"
        after = None
        while True:
            batch = list((snapshots.filter(pk__gt=after) if after else snapshots).order_by("pk")[:100])
            if not batch:
                break
            # Close the query before network I/O or tag writes; SQLite readers
            # must not remain open while a remote server responds.
            after = batch[-1].pk
            for snapshot in batch:
                result = check_snapshot(snapshot, session)
                checked += 1
                counts[result["status"]] = counts.get(result["status"], 0) + 1
                output.write(json.dumps({**result, "total": total, "checked": checked, "counts": counts}) + "\n")
                output.flush()
    output.write(json.dumps({"total": total, "checked": checked, "counts": counts, "complete": True}) + "\n")
    output.flush()
    return counts


def launch_check(*, user_id, query="", snapshot_ids=None):
    selected_ids = [UUID(str(snapshot_id)).hex for snapshot_id in snapshot_ids or []]
    process = Process(machine=Machine.current(), process_type=Process.TypeChoices.CLI, worker_type="link-check", timeout=0)
    directory = CONSTANTS.DATA_DIR / "logs" / "link-checks" / str(process.pk)
    directory.mkdir(parents=True, exist_ok=False)
    process.pwd = str(directory)
    process.cmd = [
        sys.executable,
        "-m",
        "archivebox",
        "manage",
        "linkhealth",
        "--user",
        str(user_id),
        "--query",
        query,
        "--before",
        timezone.now().isoformat(),
        "--process-id",
        str(process.pk),
    ]
    for snapshot_id in selected_ids:
        process.cmd.extend(["--snapshot", snapshot_id])
    process.save()
    return process.launch(background=True, cwd=str(CONSTANTS.DATA_DIR))


def report(process):
    """Read the existing subprocess log, keeping only the latest 100 URL results."""
    rows = deque(maxlen=100)
    progress = {"checked": 0, "total": 0, "counts": {}}
    path = process.stdout_file
    if path and path.is_file():
        with path.open(errors="replace") as source:
            for line in source:
                if not line.startswith("{"):
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "checked" in entry:
                    progress = entry
                if "snapshot_id" in entry:
                    rows.append(entry)
    return {"rows": list(reversed(rows)), **progress}
