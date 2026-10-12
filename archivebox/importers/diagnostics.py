"""Bounded, read-only access to private run artifacts, outside page rendering."""

import json
import re
import stat
from functools import lru_cache
from pathlib import Path

from archivebox.config.constants import CONSTANTS

LOG_NAME = r"(?:learning-\d+\.jsonl|replay-\d+\.log|harness\.log|failure\.log|command-error\.log|evidence\.log)"
SCREENSHOT_NAME = r"failure-[0-2]\.png"
WINDOW = 32 * 1024


def run_directory(run):
    return CONSTANTS.DATA_DIR / "importers" / str(run.source_id) / str(run.pk)


def artifact_path(run, name, pattern):
    if not re.fullmatch(pattern, name):
        raise ValueError("Unknown run artifact")
    directory = run_directory(run).resolve()
    path = directory / name
    if path.is_symlink() or path.resolve().parent != directory or not path.is_file():
        raise ValueError("Invalid run artifact")
    return path


@lru_cache(maxsize=128)
def _read(directory, files):
    sessions, logs, latest, error = [], [], {}, ""
    for name, size, mtime in files:
        path = Path(directory) / name
        try:
            with path.open("rb") as stream:
                head = stream.read(WINDOW)
                if size > WINDOW:
                    stream.seek(max(WINDOW, size - WINDOW))
                    tail = stream.read(WINDOW).split(b"\n", 1)[-1]
                else:
                    tail = b""
        except OSError:
            continue
        logs.append({"name": name, "size": size})
        if name in {"failure.log", "command-error.log"}:
            error = (tail or head).decode(errors="replace")[-4000:]
        if not name.startswith("learning-"):
            continue
        for line in (head + b"\n" + tail).splitlines():
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue  # A running process can have a partially written line.
            if not isinstance(event, dict):
                continue
            session = event.get("sessionID", "")
            if isinstance(session, str) and re.fullmatch(r"ses_[A-Za-z0-9]+", session) and session not in sessions:
                sessions.append(session)
            part = event.get("part") or {}
            if not isinstance(part, dict):
                continue
            state = part.get("state") or {}
            timestamp = event.get("timestamp", 0)
            if not isinstance(timestamp, (int, float)) or timestamp < latest.get("timestamp", 0):
                continue
            if part.get("type") == "tool" and isinstance(state, dict):
                latest = {"timestamp": timestamp, "text": f"{part.get('tool', 'Tool')}: {state.get('status', 'started')}"}
            elif part.get("type") == "text" and isinstance(part.get("text"), str):
                latest = {"timestamp": timestamp, "text": part["text"][:600]}
    return {"sessions": sessions, "logs": logs, "latest": latest.get("text", ""), "error": error}


def diagnostics(run):
    directory = run_directory(run)
    files = []
    try:
        # Only small known run logs, never the shared workspace or archive tree.
        for path in sorted(directory.iterdir()):
            if re.fullmatch(LOG_NAME, path.name) and not path.is_symlink():
                info = path.stat()
                if not stat.S_ISREG(info.st_mode):
                    continue
                files.append((path.name, info.st_size, info.st_mtime_ns))
                if len(files) == 12:
                    break
    except OSError:
        pass
    screenshots = []
    # Three bounded metadata checks; image bytes are fetched lazily through an
    # authenticated route, never read into page rendering or the log cache.
    for attempt in range(3):
        name = f"failure-{attempt}.png"
        try:
            artifact_path(run, name, SCREENSHOT_NAME)
        except (ValueError, OSError):
            continue
        screenshots.append({"name": name, "attempt": attempt})
    return {**_read(str(directory), tuple(files)), "screenshots": screenshots}
