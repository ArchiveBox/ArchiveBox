"""
Rich Layout-based live progress display for ArchiveBox orchestrator.

Shows a comprehensive dashboard with:
- Top: Crawl queue status (full width)
- Middle: 4-column grid of SnapshotWorker progress panels
- Bottom: Orchestrator/Daphne logs
"""

__package__ = 'archivebox.misc'

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from collections import deque

from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn, SpinnerColumn
from rich.table import Table
from rich.text import Text

from archivebox.config import VERSION

# Maximum number of SnapshotWorker columns to display
MAX_WORKER_COLUMNS = 4


class CrawlQueuePanel:
    """Display crawl queue status across full width."""

    def __init__(self):
        self.orchestrator_status = "Idle"
        self.crawl_queue_count = 0
        self.crawl_workers_count = 0
        self.max_crawl_workers = 8
        self.crawl_id: Optional[str] = None

    def __rich__(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right", ratio=1)

        # Left: ArchiveBox version + timestamp
        left_text = Text()
        left_text.append("ArchiveBox ", style="bold cyan")
        left_text.append(f"v{VERSION}", style="bold yellow")
        left_text.append(f" • {datetime.now(timezone.utc).strftime('%H:%M:%S')}", style="grey53")

        # Center-left: Crawl queue status
        queue_style = "yellow" if self.crawl_queue_count > 0 else "grey53"
        center_left_text = Text()
        center_left_text.append("Crawls: ", style="white")
        center_left_text.append(str(self.crawl_queue_count), style=f"bold {queue_style}")
        center_left_text.append(" queued", style="grey53")

        # Center-right: CrawlWorker status
        worker_style = "green" if self.crawl_workers_count > 0 else "grey53"
        center_right_text = Text()
        center_right_text.append("Workers: ", style="white")
        center_right_text.append(f"{self.crawl_workers_count}/{self.max_crawl_workers}", style=f"bold {worker_style}")
        center_right_text.append(" active", style="grey53")

        # Right: Orchestrator status
        status_color = "green" if self.crawl_workers_count > 0 else "grey53"
        right_text = Text()
        right_text.append("Status: ", style="white")
        right_text.append(self.orchestrator_status, style=f"bold {status_color}")
        if self.crawl_id:
            right_text.append(f" [{self.crawl_id[:8]}]", style="grey53")

        grid.add_row(left_text, center_left_text, center_right_text, right_text)
        return Panel(grid, style="white on blue", box=box.ROUNDED)


class SnapshotWorkerPanel:
    """Display progress for a single SnapshotWorker."""

    def __init__(self, worker_num: int):
        self.worker_num = worker_num
        self.snapshot_id: Optional[str] = None
        self.snapshot_url: Optional[str] = None
        self.total_hooks: int = 0
        self.completed_hooks: int = 0
        self.current_plugin: Optional[str] = None
        self.status: str = "idle"  # idle, working, completed
        self.recent_logs: deque = deque(maxlen=5)

    def __rich__(self) -> Panel:
        if self.status == "idle":
            content = Align.center(
                Text("Idle", style="grey53"),
                vertical="middle",
            )
            border_style = "grey53"
            title_style = "grey53"
        else:
            # Build progress display
            lines = []

            # URL (truncated)
            if self.snapshot_url:
                url_display = self.snapshot_url[:35] + "..." if len(self.snapshot_url) > 35 else self.snapshot_url
                lines.append(Text(url_display, style="cyan"))
                lines.append(Text())  # Spacing

            # Progress bar
            if self.total_hooks > 0:
                pct = (self.completed_hooks / self.total_hooks) * 100
                bar_width = 30
                filled = int((pct / 100) * bar_width)
                bar = "█" * filled + "░" * (bar_width - filled)

                # Color based on progress
                if pct < 30:
                    bar_style = "yellow"
                elif pct < 100:
                    bar_style = "green"
                else:
                    bar_style = "blue"

                progress_text = Text()
                progress_text.append(bar, style=bar_style)
                progress_text.append(f" {pct:.0f}%", style="white")
                lines.append(progress_text)
                lines.append(Text())  # Spacing

            # Stats
            stats = Table.grid(padding=(0, 1))
            stats.add_column(style="grey53", no_wrap=True)
            stats.add_column(style="white")
            stats.add_row("Hooks:", f"{self.completed_hooks}/{self.total_hooks}")
            if self.current_plugin:
                stats.add_row("Current:", Text(self.current_plugin, style="yellow"))
            lines.append(stats)
            lines.append(Text())  # Spacing

            # Recent logs
            if self.recent_logs:
                lines.append(Text("Recent:", style="grey53"))
                for log_msg, log_style in self.recent_logs:
                    log_text = Text(f"• {log_msg[:30]}", style=log_style)
                    lines.append(log_text)

            content = Group(*lines)
            border_style = "green" if self.status == "working" else "blue"
            title_style = "green" if self.status == "working" else "blue"

        return Panel(
            content,
            title=f"[{title_style}]Worker {self.worker_num}",
            border_style=border_style,
            box=box.ROUNDED,
            height=20,
        )

    def add_log(self, message: str, style: str = "white"):
        """Add a log message to this worker's recent logs."""
        self.recent_logs.append((message, style))


class CrawlWorkerLogPanel:
    """Display CrawlWorker logs by tailing stdout/stderr from Process."""

    def __init__(self, max_lines: int = 8):
        self.log_lines: deque = deque(maxlen=max_lines * 2)  # Allow more buffer
        self.max_lines = max_lines
        self.last_stdout_pos = 0  # Track file position for efficient tailing
        self.last_stderr_pos = 0

    def update_from_process(self, process: Any):
        """Update logs by tailing the Process stdout/stderr files."""
        from pathlib import Path

        if not process:
            return

        # Read new stdout lines since last read
        try:
            stdout_path = Path(process.stdout)
            if stdout_path.exists():
                with open(stdout_path, 'r') as f:
                    # Seek to last read position
                    f.seek(self.last_stdout_pos)
                    new_lines = f.readlines()

                    # Update position
                    self.last_stdout_pos = f.tell()

                    # Add new lines (up to max_lines to avoid overflow)
                    for line in new_lines[-self.max_lines:]:
                        line = line.rstrip('\n')
                        if line and not line.startswith('['):  # Skip Rich markup lines
                            self.log_lines.append(('stdout', line))
        except Exception:
            pass

        # Read new stderr lines since last read
        try:
            stderr_path = Path(process.stderr)
            if stderr_path.exists():
                with open(stderr_path, 'r') as f:
                    f.seek(self.last_stderr_pos)
                    new_lines = f.readlines()

                    self.last_stderr_pos = f.tell()

                    for line in new_lines[-self.max_lines:]:
                        line = line.rstrip('\n')
                        if line and not line.startswith('['):  # Skip Rich markup lines
                            self.log_lines.append(('stderr', line))
        except Exception:
            pass

    def __rich__(self) -> Panel:
        if not self.log_lines:
            content = Text("No CrawlWorker logs yet", style="grey53", justify="center")
        else:
            # Get the last max_lines for display
            display_lines = list(self.log_lines)[-self.max_lines:]
            lines = []
            for stream, message in display_lines:
                line = Text()
                # Color code by stream - stderr is usually debug output
                if stream == 'stderr':
                    # Rich formatted logs from stderr
                    line.append(message, style="cyan")
                else:
                    line.append(message, style="white")
                lines.append(line)
            content = Group(*lines)

        return Panel(
            content,
            title="[bold cyan]CrawlWorker Logs (stdout/stderr)",
            border_style="cyan",
            box=box.ROUNDED,
        )


class OrchestratorLogPanel:
    """Display orchestrator and system logs."""

    def __init__(self, max_events: int = 8):
        self.events: deque = deque(maxlen=max_events)
        self.max_events = max_events

    def add_event(self, message: str, style: str = "white"):
        """Add an event to the log."""
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.events.append((timestamp, message, style))

    def __rich__(self) -> Panel:
        if not self.events:
            content = Text("No recent events", style="grey53", justify="center")
        else:
            lines = []
            for timestamp, message, style in self.events:
                line = Text()
                line.append(f"[{timestamp}] ", style="grey53")
                line.append(message, style=style)
                lines.append(line)
            content = Group(*lines)

        return Panel(
            content,
            title="[bold white]Orchestrator / Daphne Logs",
            border_style="white",
            box=box.ROUNDED,
        )


class ArchiveBoxProgressLayout:
    """
    Main layout manager for ArchiveBox orchestrator progress display.

    Layout structure:
        ┌─────────────────────────────────────────────────────────────┐
        │              Crawl Queue (full width)                       │
        ├───────────────┬───────────────┬───────────────┬─────────────┤
        │  Snapshot     │  Snapshot     │  Snapshot     │  Snapshot   │
        │  Worker 1     │  Worker 2     │  Worker 3     │  Worker 4   │
        │               │               │               │             │
        │  Progress +   │  Progress +   │  Progress +   │  Progress + │
        │  Stats +      │  Stats +      │  Stats +      │  Stats +    │
        │  Logs         │  Logs         │  Logs         │  Logs       │
        ├───────────────┴───────────────┴───────────────┴─────────────┤
        │              CrawlWorker Logs (stdout/stderr)               │
        ├─────────────────────────────────────────────────────────────┤
        │           Orchestrator / Daphne Logs                        │
        └─────────────────────────────────────────────────────────────┘
    """

    def __init__(self, crawl_id: Optional[str] = None):
        self.crawl_id = crawl_id
        self.start_time = datetime.now(timezone.utc)

        # Create components
        self.crawl_queue = CrawlQueuePanel()
        self.crawl_queue.crawl_id = crawl_id

        # Create 4 worker panels
        self.worker_panels = [SnapshotWorkerPanel(i + 1) for i in range(MAX_WORKER_COLUMNS)]

        self.crawl_worker_log = CrawlWorkerLogPanel(max_lines=8)
        self.orchestrator_log = OrchestratorLogPanel(max_events=8)

        # Create layout
        self.layout = self._make_layout()

        # Track snapshot ID to worker panel mapping
        self.snapshot_to_worker: Dict[str, int] = {}  # snapshot_id -> worker_panel_index

    def _make_layout(self) -> Layout:
        """Define the layout structure."""
        layout = Layout(name="root")

        # Top-level split: crawl_queue, workers, logs
        layout.split(
            Layout(name="crawl_queue", size=3),
            Layout(name="workers", ratio=1),
            Layout(name="logs", size=20),
        )

        # Split workers into 4 columns
        layout["workers"].split_row(
            Layout(name="worker1"),
            Layout(name="worker2"),
            Layout(name="worker3"),
            Layout(name="worker4"),
        )

        # Split logs into crawl_worker_logs and orchestrator_logs
        layout["logs"].split(
            Layout(name="crawl_worker_logs", size=10),
            Layout(name="orchestrator_logs", size=10),
        )

        # Assign components to layout sections
        layout["crawl_queue"].update(self.crawl_queue)
        layout["worker1"].update(self.worker_panels[0])
        layout["worker2"].update(self.worker_panels[1])
        layout["worker3"].update(self.worker_panels[2])
        layout["worker4"].update(self.worker_panels[3])
        layout["crawl_worker_logs"].update(self.crawl_worker_log)
        layout["orchestrator_logs"].update(self.orchestrator_log)

        return layout

    def update_orchestrator_status(
        self,
        status: str,
        crawl_queue_count: int = 0,
        crawl_workers_count: int = 0,
        max_crawl_workers: int = 8,
    ):
        """Update orchestrator status in the crawl queue panel."""
        self.crawl_queue.orchestrator_status = status
        self.crawl_queue.crawl_queue_count = crawl_queue_count
        self.crawl_queue.crawl_workers_count = crawl_workers_count
        self.crawl_queue.max_crawl_workers = max_crawl_workers

    def update_snapshot_worker(
        self,
        snapshot_id: str,
        url: str,
        total: int,
        completed: int,
        current_plugin: str = "",
    ):
        """Update or assign a snapshot to a worker panel."""
        # Find or assign worker panel for this snapshot
        if snapshot_id not in self.snapshot_to_worker:
            # Find first idle worker panel
            worker_idx = None
            for idx, panel in enumerate(self.worker_panels):
                if panel.status == "idle":
                    worker_idx = idx
                    break

            # If no idle worker, use round-robin (shouldn't happen often)
            if worker_idx is None:
                worker_idx = len(self.snapshot_to_worker) % MAX_WORKER_COLUMNS

            self.snapshot_to_worker[snapshot_id] = worker_idx

        # Get assigned worker panel
        worker_idx = self.snapshot_to_worker[snapshot_id]
        panel = self.worker_panels[worker_idx]

        # Update panel
        panel.snapshot_id = snapshot_id
        panel.snapshot_url = url
        panel.total_hooks = total
        panel.completed_hooks = completed
        panel.current_plugin = current_plugin
        panel.status = "working" if completed < total else "completed"

    def remove_snapshot_worker(self, snapshot_id: str):
        """Mark a snapshot worker as idle after completion."""
        if snapshot_id in self.snapshot_to_worker:
            worker_idx = self.snapshot_to_worker[snapshot_id]
            panel = self.worker_panels[worker_idx]

            # Mark as idle
            panel.status = "idle"
            panel.snapshot_id = None
            panel.snapshot_url = None
            panel.total_hooks = 0
            panel.completed_hooks = 0
            panel.current_plugin = None
            panel.recent_logs.clear()

            # Remove mapping
            del self.snapshot_to_worker[snapshot_id]

    def log_to_worker(self, snapshot_id: str, message: str, style: str = "white"):
        """Add a log message to a specific worker's panel."""
        if snapshot_id in self.snapshot_to_worker:
            worker_idx = self.snapshot_to_worker[snapshot_id]
            self.worker_panels[worker_idx].add_log(message, style)

    def log_event(self, message: str, style: str = "white"):
        """Add an event to the orchestrator log."""
        self.orchestrator_log.add_event(message, style)

    def update_crawl_worker_logs(self, process: Any):
        """Update CrawlWorker logs by tailing the Process stdout/stderr files."""
        self.crawl_worker_log.update_from_process(process)

    def get_layout(self) -> Layout:
        """Get the Rich Layout object for rendering."""
        return self.layout
