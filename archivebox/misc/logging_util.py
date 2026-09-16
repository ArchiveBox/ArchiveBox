__package__ = "archivebox"

# Post-bootstrap CLI logging helpers (event loggers, progress bars, formatters).
# Requires archivebox.config to be loaded — imports CONSTANTS/get_config and
# references Django ORM types. For pre-bootstrap logging primitives use
# misc/logging.py, which has no archivebox or Django dependencies.

import os
import sys
import time

from pathlib import Path

from typing import Any, TYPE_CHECKING, cast

if TYPE_CHECKING:
    pass

from rich import print

from archivebox.config import CONSTANTS
from archivebox.misc.util import enforce_types


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


def _warn_background_cleanup(context: str, err: BaseException) -> None:
    from archivebox.misc.logging import STDERR

    STDERR.print(f"[yellow][!] {context}: {err!s}[/yellow]")


def tail_multiple_worker_logs(log_files: list[str], follow=True, proc=None, keep_running=None):
    """Tail multiple log files simultaneously, interleaving their output.

    Args:
        log_files: List of log file paths to tail
        follow: Whether to keep following (True) or just read existing content (False)
        proc: Optional subprocess.Popen object - stop tailing when this process exits
    """
    import re
    from archivebox.config.common import rprint as print

    # Convert relative paths to absolute paths
    log_paths = []
    for log_file in log_files:
        log_path = Path(log_file)
        if not log_path.is_absolute():
            log_path = CONSTANTS.DATA_DIR / log_path

        # Create log file if it doesn't exist
        if not log_path.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch()

        log_paths.append(log_path)

    # Open all log files
    file_handles = []
    for log_path in log_paths:
        try:
            f = log_path.open()
            # Seek to end - only show NEW logs from now on, not old logs
            f.seek(0, 2)  # Go to end

            file_handles.append((log_path, f))
            print(f"    [tailing {log_path.name}]")
        except OSError as e:
            sys.stderr.write(f"Warning: Could not open {log_path}: {e}\n")

    if not file_handles:
        sys.stderr.write("No log files could be opened\n")
        return

    print()

    try:
        while follow:
            if keep_running is not None and not keep_running():
                print("\n[newer ArchiveBox process is now running the orchestrator and server]")
                return "transferred"

            # Check if the monitored process has exited
            if proc is not None and proc.poll() is not None:
                print(f"\n[server process exited with code {proc.returncode}]")
                return "exited"

            had_output = False
            # Read ALL available lines from all files (not just one per iteration)
            for log_path, f in file_handles:
                while True:
                    line = f.readline()
                    if not line:
                        break  # No more lines available in this file
                    had_output = True
                    # Strip ANSI codes if present (supervisord does this but just in case)
                    line_clean = re.sub(r"\x1b\[[0-9;]*m", "", line.rstrip())
                    if line_clean:
                        print(line_clean)

            # Small sleep to avoid busy-waiting (only when no output)
            if not had_output:
                time.sleep(0.05)

    except (KeyboardInterrupt, BrokenPipeError, OSError):
        return "interrupted"  # Let the caller handle the cleanup message
    except SystemExit:
        return "interrupted"
    finally:
        # Close all file handles
        for _, f in file_handles:
            try:
                f.close()
            except OSError as err:
                _warn_background_cleanup("Could not close worker log file", err)
    return "stopped"
