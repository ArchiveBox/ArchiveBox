__package__ = "archivebox"

# Post-bootstrap CLI logging helpers (event loggers, progress bars, formatters).
# Requires archivebox.config to be loaded — imports CONSTANTS/get_config and
# references Django ORM types. For pre-bootstrap logging primitives use
# misc/logging.py, which has no archivebox or Django dependencies.

import re
import os
import sys
import time

from math import log
from multiprocessing import Process
from pathlib import Path

from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from archivebox.core.models import Snapshot

from rich import print

from archivebox.config import CONSTANTS
from archivebox.config.common import get_config
from archivebox.misc.util import enforce_types
from archivebox.misc.logging import ANSI


class TimedProgress:
    """Show a progress bar and measure elapsed time until .end() is called"""

    def __init__(self, seconds, prefix="", config=None, **config_kwargs):

        config = config or get_config(**config_kwargs)
        self.SHOW_PROGRESS = config.SHOW_PROGRESS
        self.ANSI = config.ANSI
        self.TERM_WIDTH = config.TERM_WIDTH

        if self.SHOW_PROGRESS:
            self.p = Process(target=progress_bar, args=(seconds, prefix, self.ANSI))
            self.p.start()

        self.stats = {"start_ts": datetime.now(timezone.utc), "end_ts": None}

    def end(self):
        """immediately end progress, clear the progressbar line, and save end_ts"""

        end_ts = datetime.now(timezone.utc)
        self.stats["end_ts"] = end_ts

        if self.SHOW_PROGRESS:
            # terminate if we havent already terminated
            try:
                # kill the progress bar subprocess
                try:
                    self.p.close()  # must be closed *before* its terminnated
                except (KeyboardInterrupt, SystemExit):
                    print()
                    raise
                except BaseException:  # lgtm [py/catch-base-exception]
                    pass
                self.p.terminate()
                time.sleep(0.1)
                # sometimes the timer doesn't terminate properly, then blocks at the join until
                # the full time has elapsed. sending a kill tries to avoid that.
                try:
                    self.p.kill()
                except Exception:
                    pass

                # clear whole terminal line
                try:
                    sys.stdout.write("\r{}{}\r".format((" " * self.TERM_WIDTH), self.ANSI["reset"]))
                except (OSError, BrokenPipeError):
                    # ignore when the parent proc has stopped listening to our stdout
                    pass
            except ValueError:
                pass


@enforce_types
def progress_bar(seconds: int, prefix: str = "", ANSI: dict[str, str] = ANSI, config=None, **config_kwargs) -> None:
    """show timer in the form of progress bar, with percentage and seconds remaining"""
    output_buf = sys.stdout or sys.__stdout__ or sys.stderr or sys.__stderr__
    chunk = "█" if output_buf and output_buf.encoding.upper() == "UTF-8" else "#"
    config = config or get_config(**config_kwargs)
    last_width = config.TERM_WIDTH
    chunks = last_width - len(prefix) - 20  # number of progress chunks to show (aka max bar width)
    try:
        for s in range(seconds * chunks):
            max_width = config.TERM_WIDTH
            if max_width < last_width:
                # when the terminal size is shrunk, we have to write a newline
                # otherwise the progress bar will keep wrapping incorrectly
                sys.stdout.write("\r\n")
                sys.stdout.flush()
            chunks = max_width - len(prefix) - 20
            pct_complete = s / chunks / seconds * 100
            log_pct = (log(pct_complete or 1, 10) / 2) * 100  # everyone likes faster progress bars ;)
            bar_width = round(log_pct / (100 / chunks))
            last_width = max_width

            # ████████████████████           0.9% (1/60sec)
            sys.stdout.write(
                "\r{}{}{}{} {}% ({}/{}sec)".format(
                    prefix,
                    ANSI["green" if pct_complete < 80 else "lightyellow"],
                    (chunk * bar_width).ljust(chunks),
                    ANSI["reset"],
                    round(pct_complete, 1),
                    round(s / chunks),
                    seconds,
                ),
            )
            sys.stdout.flush()
            time.sleep(1 / chunks)

        # ██████████████████████████████████ 100.0% (60/60sec)
        sys.stdout.write(
            "\r{}{}{}{} {}% ({}/{}sec)".format(
                prefix,
                ANSI["red"],
                chunk * chunks,
                ANSI["reset"],
                100.0,
                seconds,
                seconds,
            ),
        )
        sys.stdout.flush()
    except (KeyboardInterrupt, BrokenPipeError):
        print()


def log_list_started(filter_patterns: list[str] | None, filter_type: str):
    print(f"[green][*] Finding links in the archive index matching these {filter_type} patterns:[/]")
    print("    {}".format(" ".join(filter_patterns or ())))


def log_list_finished(snapshots):
    from archivebox.core.models import Snapshot

    print()
    print("---------------------------------------------------------------------------------------------------")
    csv_queryset = cast(Any, Snapshot.objects.filter(pk__in=[s.pk for s in snapshots]))
    print(csv_queryset.to_csv(cols=["timestamp", "is_archived", "num_outputs", "url"], header=True, ljust=16, separator=" | "))
    print("---------------------------------------------------------------------------------------------------")
    print()


def log_removal_started(snapshots, yes: bool):
    from django.db.models import QuerySet

    count = snapshots.count() if isinstance(snapshots, QuerySet) else len(snapshots)
    print(f"[yellow3][i] Found {count} matching URLs to remove.[/]")
    file_counts = [s.num_outputs for s in snapshots if os.access(s.output_dir, os.R_OK)]
    print(
        f"    {count} Links will be deleted from the index and their archived content folders will be deleted from disk.\n"
        f"    ({len(file_counts)} data folders with {sum(file_counts)} archived files will be deleted!)",
    )

    if not yes:
        print()
        print(f"[yellow3][?] Do you want to proceed with removing these {count} links?[/]")
        try:
            assert input("    y/[n]: ").lower() == "y"
        except (KeyboardInterrupt, EOFError, AssertionError):
            raise SystemExit(0)


def log_removal_finished(remaining_links: int, removed_links: int):
    if remaining_links == 0 and removed_links == 0:
        print()
        print("[red1][X] No matching links found.[/]")
    else:
        total_before = remaining_links + removed_links
        print()
        print(f"[red1][√] Removed {removed_links} out of {total_before} links from the archive index.[/]")
        print(f"    Index now contains {remaining_links} links.")


### Helpers


@enforce_types
def pretty_path(path: Path | str, pwd: Path | str = CONSTANTS.DATA_DIR, color: bool = True) -> str:
    """convert paths like .../ArchiveBox/archivebox/../output/abc into output/abc"""
    pwd = str(Path(pwd))  # .resolve()
    path = str(path)

    if not path:
        return path

    # replace long absolute paths with ./ relative ones to save on terminal output width
    if path.startswith(pwd) and (pwd != "/") and path != pwd:
        if color:
            path = path.replace(pwd, "[light_slate_blue].[/light_slate_blue]", 1)
        else:
            path = path.replace(pwd, ".", 1)

    # quote paths containing spaces
    if " " in path:
        path = f'"{path}"'

    # replace home directory with ~ for shorter output
    path = path.replace(str(Path("~").expanduser()), "~")

    return path


@enforce_types
def printable_filesize(num_bytes: int | float) -> str:
    for count in ["Bytes", "KB", "MB", "GB"]:
        if num_bytes > -1024.0 and num_bytes < 1024.0:
            return f"{num_bytes:3.1f} {count}"
        num_bytes /= 1024.0
    return "{:3.1f} {}".format(num_bytes, "TB")


@enforce_types
def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}min {secs}s" if secs else f"{minutes}min"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}hr {minutes}min" if minutes else f"{hours}hr"


@enforce_types
def truncate_url(url: str, max_length: int = 60) -> str:
    """Truncate URL to max_length, keeping domain and adding ellipsis."""
    if len(url) <= max_length:
        return url
    # Try to keep the domain and beginning of path
    if "://" in url:
        protocol, rest = url.split("://", 1)
        if "/" in rest:
            domain, path = rest.split("/", 1)
            available = max_length - len(protocol) - len(domain) - 6  # for "://", "/", "..."
            if available > 10:
                return f"{protocol}://{domain}/{path[:available]}..."
    # Fallback: just truncate
    return url[: max_length - 3] + "..."


@enforce_types
def log_worker_event(
    worker_type: str,
    event: str,
    indent_level: int = 0,
    pid: int | None = None,
    worker_id: str | None = None,
    url: str | None = None,
    plugin: str | None = None,
    metadata: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    """
    Log a worker event with structured metadata and indentation.

    Args:
        worker_type: Type of worker (Orchestrator, CrawlWorker, SnapshotWorker)
        event: Event name (Starting, Completed, Failed, etc.)
        indent_level: Indentation level (0=Orchestrator, 1=CrawlWorker, 2=SnapshotWorker)
        pid: Process ID
        worker_id: Worker ID (UUID for workers)
        url: URL being processed (for SnapshotWorker)
        plugin: Plugin name (for hook processes)
        metadata: Dict of metadata to show in curly braces
        error: Exception if event is an error
    """
    indent = "    " * indent_level

    from rich.markup import escape

    # Build worker identifier (without URL/plugin)
    worker_parts = [worker_type]
    # Don't add pid/worker_id for DB operations (they happen in whatever process is running)
    if pid and worker_type != "DB":
        worker_parts.append(f"pid={pid}")
    if worker_id and worker_type in ("CrawlWorker", "Orchestrator") and worker_type != "DB":
        worker_parts.append(f"id={worker_id}")

    # Build worker label parts for brackets (shown inside brackets)
    worker_label_base = worker_parts[0]
    worker_bracket_content = ", ".join(worker_parts[1:]) if len(worker_parts) > 1 else None

    # Build URL/plugin display (shown AFTER the label, outside brackets)
    url_extractor_parts = []
    if url:
        url_extractor_parts.append(f"url: {escape(url)}")
    if plugin:
        url_extractor_parts.append(f"extractor: {escape(plugin)}")

    url_extractor_str = " | ".join(url_extractor_parts) if url_extractor_parts else ""

    # Build metadata string
    metadata_str = ""
    if metadata:
        # Format metadata nicely
        meta_parts = []
        for k, v in metadata.items():
            if isinstance(v, float):
                # Format floats nicely (durations, sizes)
                if "duration" in k.lower():
                    meta_parts.append(f"{k}: {format_duration(v)}")
                elif "size" in k.lower():
                    meta_parts.append(f"{k}: {printable_filesize(int(v))}")
                else:
                    meta_parts.append(f"{k}: {v:.2f}")
            elif isinstance(v, int):
                # Format integers - check if it's a size
                if "size" in k.lower() or "bytes" in k.lower():
                    meta_parts.append(f"{k}: {printable_filesize(v)}")
                else:
                    meta_parts.append(f"{k}: {v}")
            elif isinstance(v, (list, tuple)):
                meta_parts.append(f"{k}: {len(v)}")
            else:
                meta_parts.append(f"{k}: {v}")
        metadata_str = " | ".join(meta_parts)

    # Determine color based on event
    color = "white"
    if event in ("Starting...", "Started", "STARTED", "Started in background"):
        color = "green"
    elif event.startswith("Created"):
        color = "cyan"  # DB creation events
    elif event in ("Completed", "COMPLETED", "All work complete"):
        color = "blue"
    elif event in ("Failed", "ERROR", "Failed to spawn worker"):
        color = "red"
    elif event in ("Shutting down", "SHUTDOWN"):
        color = "grey53"

    # Build final message
    error_str = f" {type(error).__name__}: {error}" if error else ""
    from archivebox.misc.logging import CONSOLE, STDERR
    from rich.text import Text

    # Create a Rich Text object for proper formatting
    # Text.append() treats content as literal (no markup parsing)
    text = Text()
    text.append(indent)
    text.append(worker_label_base, style=color)

    # Add bracketed content if present (using Text.append to avoid markup issues)
    if worker_bracket_content:
        text.append("[", style=color)
        text.append(worker_bracket_content, style=color)
        text.append("]", style=color)

    text.append(f" {event}{error_str}", style=color)

    # Add URL/plugin info first (more important)
    if url_extractor_str:
        text.append(f" | {url_extractor_str}")

    # Then add other metadata
    if metadata_str:
        text.append(f" | {metadata_str}")

    # Stdout is reserved for JSONL records whenever commands are piped together.
    # Route worker/DB progress to stderr in non-TTY contexts so pipelines like
    # `archivebox snapshot list | archivebox run` keep stdout machine-readable.
    output_console = CONSOLE if sys.stdout.isatty() else STDERR
    output_console.print(text, soft_wrap=True)


@enforce_types
def printable_folders(folders: dict[str, Optional["Snapshot"]], with_headers: bool = False) -> str:
    return "\n".join(f'{folder} {snapshot and snapshot.url} "{snapshot and snapshot.title}"' for folder, snapshot in folders.items())


@enforce_types
def printable_config(config: dict, prefix: str = "") -> str:
    return f"\n{prefix}".join(f"{key}={val}" for key, val in config.items() if not (isinstance(val, dict) or callable(val)))


@enforce_types
def printable_folder_status(name: str, folder: dict) -> str:
    if folder["enabled"]:
        if folder["is_valid"]:
            color, symbol, note, num_files = "green", "√", "valid", ""
        else:
            color, symbol, note, num_files = "red", "X", "invalid", "?"
    else:
        color, symbol, note, num_files = "grey53", "-", "unused", "-"

    if folder["path"] and "://" not in str(folder["path"]):
        # file-count probing only makes sense for filesystem paths, not DSNs
        if os.access(folder["path"], os.R_OK):
            try:
                num_files = (
                    f"{len(os.listdir(folder['path']))} files"
                    if os.path.isdir(folder["path"])
                    else printable_filesize(Path(folder["path"]).stat().st_size)
                )
            except PermissionError:
                num_files = "error"
        else:
            num_files = "missing"

    if folder.get("is_mount"):
        # add symbol @ next to filecount if path is a remote filesystem mount
        num_files = f"{num_files} @" if num_files else "@"

    path = pretty_path(folder["path"])

    return " ".join(
        (
            f"[{color}]",
            symbol,
            "[/]",
            name.ljust(21).replace("DATA_DIR", "[light_slate_blue]DATA_DIR[/light_slate_blue]"),
            num_files.ljust(14).replace("missing", "[grey53]missing[/grey53]"),
            f"[{color}]",
            note.ljust(8),
            "[/]",
            path.ljust(76),
        ),
    )


@enforce_types
def printable_dependency_version(name: str, dependency: dict) -> str:
    color, symbol, note, version = "red", "X", "invalid", "?"

    if dependency["enabled"]:
        if dependency["is_valid"]:
            color, symbol, note = "green", "√", "valid"

            parsed_version_num = re.search(r"[\d\.]+", dependency["version"])
            if parsed_version_num:
                version = f"v{parsed_version_num[0]}"
    else:
        color, symbol, note, version = "lightyellow", "-", "disabled", "-"

    path = pretty_path(dependency["path"])

    return " ".join(
        (
            ANSI[color],
            symbol,
            ANSI["reset"],
            name.ljust(21),
            version.ljust(14),
            ANSI[color],
            note.ljust(8),
            ANSI["reset"],
            path.ljust(76),
        ),
    )
