from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console


class LiveBusUI:
    """Small tty-only runner UI.

    The runner only needs a context manager and a couple of print helpers here.
    Keeping this minimal avoids a hard dependency on a heavier live dashboard.
    """

    def __init__(
        self,
        bus: Any,
        *,
        total_hooks: int,
        timeout_seconds: int,
        ui_console: Console,
        interactive_tty: bool,
    ) -> None:
        self.bus = bus
        self.total_hooks = total_hooks
        self.timeout_seconds = timeout_seconds
        self.ui_console = ui_console
        self.interactive_tty = interactive_tty

    def __enter__(self) -> LiveBusUI:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def print_intro(self, *, url: str, output_dir: Path, plugins_label: str) -> None:
        if not self.interactive_tty:
            return
        self.ui_console.print(
            f"[bold]ArchiveBox[/bold] {url} -> [dim]{output_dir}[/dim] "
            f"([cyan]{plugins_label}[/cyan], {self.total_hooks} hooks, {self.timeout_seconds}s timeout)",
        )

    def print_summary(self, results: list[Any] | tuple[Any, ...] | None, *, output_dir: Path) -> None:
        if not self.interactive_tty:
            return
        total_results = len(results or [])
        self.ui_console.print(
            f"[green]Completed[/green] {total_results} result(s) in [dim]{output_dir}[/dim]",
        )
