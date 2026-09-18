from __future__ import annotations
import os
import sys
import shutil
from rich.console import Console
from rich.text import Text
from abx_dl.catalog import PluginCatalog


def _runner_short_id(identifier) -> str:
    return str(identifier).replace("-", "")[-8:]


def _runner_label(value: str, *, reserve: int) -> str:
    width = max(24, shutil.get_terminal_size(fallback=(120, 40)).columns - reserve)
    value = " ".join(str(value or "").split())
    if len(value) <= width:
        return value
    return f"{value[: max(0, width - 3)]}..."


def _runner_console_line(*, crawl=None, crawl_id=None, snapshot=None, status: str = "STARTED") -> None:
    crawl_id = crawl.id if crawl is not None else crawl_id
    line = Text()
    line.append(f"[Crawl#{_runner_short_id(crawl_id)}]", style="cyan bold")
    line.append(" ")
    if snapshot is not None:
        line.append(f"[Snapshot#{_runner_short_id(snapshot.id)}]", style="magenta bold")
        line.append(" ")
    status_styles = {
        "STARTED": "green bold",
        "SEALED": "blue bold",
        "PAUSED": "yellow bold",
    }
    line.append(f"[{status}]", style=status_styles.get(status, "white bold"))
    line.append(" ")
    prefix_width = len(line.plain)
    if snapshot is not None:
        label = snapshot.url
    else:
        label = (crawl.label or "").strip()
        if not label:
            label = (crawl.urls or "").partition("\n")[0].strip() or str(crawl_id)
    line.append(_runner_label(label, reserve=prefix_width))
    Console(highlight=False).print(line)


def _count_selected_hooks(catalog: PluginCatalog, selected_plugins: list[str] | None) -> int:
    selected = catalog.select(selected_plugins) if selected_plugins else catalog
    return sum(1 for plugin in selected.values() for hook in plugin.hooks if "CrawlSetup" in hook.name or "Snapshot" in hook.name)


def create_console():
    """Build a correctly sized progress console and return its owned tty stream.

    Callers close only the returned stream; stdout/stderr belong to the process.
    A crawl may use this console noninteractively, while installation displays
    the live UI only when a terminal is attached.
    """
    stdout_is_tty = sys.stdout.isatty()
    stderr_is_tty = sys.stderr.isatty()
    interactive = stdout_is_tty or stderr_is_tty
    stream = sys.stderr if stderr_is_tty or not stdout_is_tty else sys.stdout
    owned_stream = None
    if interactive and os.path.exists("/dev/tty"):
        try:
            owned_stream = open("/dev/tty", "w", buffering=1, encoding=stream.encoding or "utf-8")
            stream = owned_stream
        except OSError:
            pass
    try:
        size = os.get_terminal_size(stream.fileno())
    except (AttributeError, OSError, ValueError):
        size = shutil.get_terminal_size(fallback=(160, 40))
    console = Console(
        file=stream,
        force_terminal=interactive,
        width=size.columns,
        height=size.lines,
        _environ={"COLUMNS": str(size.columns), "LINES": str(size.lines)},
    )
    return console, owned_stream, interactive
