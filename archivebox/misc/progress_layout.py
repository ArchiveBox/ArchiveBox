"""
Rich Layout-based live progress display for ArchiveBox orchestrator.

Shows a comprehensive dashboard with:
- Top: Crawl queue status (full width)
- Middle: Running process logs (dynamic panels)
- Bottom: Orchestrator/Daphne logs
"""

__package__ = 'archivebox.misc'

from datetime import datetime, timezone
from typing import List, Optional, Any
from collections import deque
from pathlib import Path

from rich import box
from rich.align import Align
from rich.console import Group
from rich.layout import Layout
from rich.columns import Columns
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.tree import Tree

from archivebox.config import VERSION


class CrawlQueuePanel:
    """Display crawl queue status across full width."""

    def __init__(self):
        self.orchestrator_status = "Idle"
        self.crawl_queue_count = 0
        self.crawl_workers_count = 0
        self.binary_queue_count = 0
        self.binary_workers_count = 0
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

        # Center-left: Crawl + Binary queue status
        queue_style = "yellow" if self.crawl_queue_count > 0 else "grey53"
        center_left_text = Text()
        center_left_text.append("Crawls: ", style="white")
        center_left_text.append(str(self.crawl_queue_count), style=f"bold {queue_style}")
        center_left_text.append(" queued", style="grey53")
        center_left_text.append(" • Binaries: ", style="white")
        binary_queue_style = "yellow" if self.binary_queue_count > 0 else "grey53"
        center_left_text.append(str(self.binary_queue_count), style=f"bold {binary_queue_style}")
        center_left_text.append(" queued", style="grey53")

        # Center-right: Worker status
        worker_style = "green" if self.crawl_workers_count > 0 else "grey53"
        center_right_text = Text()
        center_right_text.append("Workers: ", style="white")
        center_right_text.append(f"{self.crawl_workers_count}/{self.max_crawl_workers}", style=f"bold {worker_style}")
        center_right_text.append(" crawl", style="grey53")
        binary_worker_style = "green" if self.binary_workers_count > 0 else "grey53"
        center_right_text.append(" • ", style="grey53")
        center_right_text.append(str(self.binary_workers_count), style=f"bold {binary_worker_style}")
        center_right_text.append(" binary", style="grey53")

        # Right: Orchestrator status
        status_color = "green" if self.crawl_workers_count > 0 else "grey53"
        right_text = Text()
        right_text.append("Status: ", style="white")
        right_text.append(self.orchestrator_status, style=f"bold {status_color}")
        if self.crawl_id:
            right_text.append(f" [{self.crawl_id[:8]}]", style="grey53")

        grid.add_row(left_text, center_left_text, center_right_text, right_text)
        return Panel(grid, style="white on blue", box=box.HORIZONTALS)


class ProcessLogPanel:
    """Display logs for a running Process."""

    def __init__(self, process: Any, max_lines: int = 8, compact: bool | None = None):
        self.process = process
        self.max_lines = max_lines
        self.compact = compact

    def __rich__(self) -> Panel:
        is_pending = self._is_pending()
        output_line = '' if is_pending else self._output_line()
        stdout_lines = []
        stderr_lines = []
        try:
            stdout_lines = list(self.process.tail_stdout(lines=self.max_lines, follow=False))
            stderr_lines = list(self.process.tail_stderr(lines=self.max_lines, follow=False))
        except Exception:
            stdout_lines = []
            stderr_lines = []

        header_lines = []
        chrome_launch_line = self._chrome_launch_line(stderr_lines, stdout_lines)
        if chrome_launch_line:
            header_lines.append(Text(chrome_launch_line, style="grey53"))
        if output_line:
            header_lines.append(Text(output_line, style="grey53"))
        log_lines = []
        for line in stdout_lines:
            if line:
                log_lines.append(Text(line, style="white"))
        for line in stderr_lines:
            if line:
                log_lines.append(Text(line, style="cyan"))

        compact = self.compact if self.compact is not None else self._is_background_hook()
        max_body = max(1, self.max_lines - len(header_lines))
        if not log_lines:
            log_lines = []

        lines = header_lines + log_lines[-max_body:]

        content = Group(*lines) if lines else Text("")

        title = self._title()
        border_style = "grey53" if is_pending else "cyan"
        height = 2 if is_pending else None
        return Panel(
            content,
            title=title,
            border_style=border_style,
            box=box.HORIZONTALS,
            padding=(0, 1),
            height=height,
        )

    def _title(self) -> str:
        process_type = getattr(self.process, 'process_type', 'process')
        worker_type = getattr(self.process, 'worker_type', '')
        pid = getattr(self.process, 'pid', None)
        label = process_type
        if process_type == 'worker' and worker_type:
            label, worker_suffix = self._worker_label(worker_type)
        elif process_type == 'hook':
            try:
                cmd = getattr(self.process, 'cmd', [])
                hook_path = Path(cmd[1]) if len(cmd) > 1 else None
                hook_name = hook_path.name if hook_path else 'hook'
                plugin_name = hook_path.parent.name if hook_path and hook_path.parent.name else 'hook'
            except Exception:
                hook_name = 'hook'
                plugin_name = 'hook'
            label = f"{plugin_name}/{hook_name}"
            worker_suffix = ''
        else:
            worker_suffix = ''

        url = self._extract_url()
        url_suffix = f" url={self._abbrev_url(url)}" if url else ""
        time_suffix = self._elapsed_suffix()
        title_style = "grey53" if self._is_pending() else "bold white"
        if pid:
            return f"[{title_style}]{label}[/{title_style}] [grey53]pid={pid}{worker_suffix}{url_suffix}{time_suffix}[/grey53]"
        return f"[{title_style}]{label}[/{title_style}]{f' [grey53]{worker_suffix.strip()} {url_suffix.strip()}{time_suffix}[/grey53]' if (worker_suffix or url_suffix or time_suffix) else ''}".rstrip()

    def _is_background_hook(self) -> bool:
        if getattr(self.process, 'process_type', '') != 'hook':
            return False
        try:
            cmd = getattr(self.process, 'cmd', [])
            hook_path = Path(cmd[1]) if len(cmd) > 1 else None
            hook_name = hook_path.name if hook_path else ''
            return '.bg.' in hook_name
        except Exception:
            return False

    def _is_pending(self) -> bool:
        status = getattr(self.process, 'status', '')
        if status in ('queued', 'pending', 'backoff'):
            return True
        if getattr(self.process, 'process_type', '') == 'hook' and not getattr(self.process, 'pid', None):
            return True
        return False

    def _worker_label(self, worker_type: str) -> tuple[str, str]:
        cmd = getattr(self.process, 'cmd', []) or []
        if worker_type == 'crawl':
            crawl_id = self._extract_arg(cmd, '--crawl-id')
            suffix = ''
            if crawl_id:
                suffix = f" id={str(crawl_id)[-8:]}"
                try:
                    from archivebox.crawls.models import Crawl
                    crawl = Crawl.objects.filter(id=crawl_id).first()
                    if crawl:
                        urls = crawl.get_urls_list()
                        if urls:
                            url_list = self._abbrev_urls(urls)
                            suffix += f" urls={url_list}"
                except Exception:
                    pass
            return 'crawl', suffix
        if worker_type == 'snapshot':
            snapshot_id = self._extract_arg(cmd, '--snapshot-id')
            suffix = ''
            if snapshot_id:
                suffix = f" id={str(snapshot_id)[-8:]}"
                try:
                    from archivebox.core.models import Snapshot
                    snap = Snapshot.objects.filter(id=snapshot_id).first()
                    if snap and snap.url:
                        suffix += f" url={self._abbrev_url(snap.url, max_len=48)}"
                except Exception:
                    pass
            return 'snapshot', suffix
        return f"worker:{worker_type}", ''

    @staticmethod
    def _extract_arg(cmd: list[str], key: str) -> str | None:
        for i, part in enumerate(cmd):
            if part.startswith(f'{key}='):
                return part.split('=', 1)[1]
            if part == key and i + 1 < len(cmd):
                return cmd[i + 1]
        return None

    def _abbrev_urls(self, urls: list[str], max_len: int = 48) -> str:
        if not urls:
            return ''
        if len(urls) == 1:
            return self._abbrev_url(urls[0], max_len=max_len)
        first = self._abbrev_url(urls[0], max_len=max_len)
        return f"{first},+{len(urls) - 1}"

    def _extract_url(self) -> str:
        url = getattr(self.process, 'url', None)
        if url:
            return str(url)
        cmd = getattr(self.process, 'cmd', []) or []
        for i, part in enumerate(cmd):
            if part.startswith('--url='):
                return part.split('=', 1)[1].strip()
            if part == '--url' and i + 1 < len(cmd):
                return str(cmd[i + 1]).strip()
        return ''

    def _abbrev_url(self, url: str, max_len: int = 48) -> str:
        if not url:
            return ''
        if len(url) <= max_len:
            return url
        return f"{url[:max_len - 3]}..."

    def _chrome_launch_line(self, stderr_lines: list[str], stdout_lines: list[str]) -> str:
        try:
            cmd = getattr(self.process, 'cmd', [])
            hook_path = Path(cmd[1]) if len(cmd) > 1 else None
            hook_name = hook_path.name if hook_path else ''
            if 'chrome_launch' not in hook_name:
                return ''

            pid = ''
            ws = ''
            for line in stderr_lines + stdout_lines:
                if not ws and 'CDP URL:' in line:
                    ws = line.split('CDP URL:', 1)[1].strip()
                if not pid and 'PID:' in line:
                    pid = line.split('PID:', 1)[1].strip()

            if pid and ws:
                return f"Chrome pid={pid} {ws}"
            if ws:
                return f"Chrome {ws}"
            if pid:
                return f"Chrome pid={pid}"
            try:
                from archivebox import DATA_DIR
                base = Path(DATA_DIR)
                pwd = getattr(self.process, 'pwd', None)
                if pwd:
                    chrome_dir = Path(pwd)
                    if not chrome_dir.is_absolute():
                        chrome_dir = (base / chrome_dir).resolve()
                    cdp_file = chrome_dir / 'cdp_url.txt'
                    pid_file = chrome_dir / 'chrome.pid'
                    if cdp_file.exists():
                        ws = cdp_file.read_text().strip()
                    if pid_file.exists():
                        pid = pid_file.read_text().strip()
                    if pid and ws:
                        return f"Chrome pid={pid} {ws}"
                    if ws:
                        return f"Chrome {ws}"
                    if pid:
                        return f"Chrome pid={pid}"
            except Exception:
                pass
        except Exception:
            return ''
        return ''

    def _elapsed_suffix(self) -> str:
        started_at = getattr(self.process, 'started_at', None)
        timeout = getattr(self.process, 'timeout', None)
        if not started_at or not timeout:
            return ''
        try:
            now = datetime.now(timezone.utc) if started_at.tzinfo else datetime.now()
            elapsed = int((now - started_at).total_seconds())
            elapsed = max(elapsed, 0)
            return f" [{elapsed}/{int(timeout)}s]"
        except Exception:
            return ''

    def _output_line(self) -> str:
        pwd = getattr(self.process, 'pwd', None)
        if not pwd:
            return ''
        try:
            from archivebox import DATA_DIR
            rel = Path(pwd)
            base = Path(DATA_DIR)
            if rel.is_absolute():
                try:
                    rel = rel.relative_to(base)
                except Exception:
                    pass
            rel_str = f"./{rel}" if not str(rel).startswith("./") else str(rel)
            return f"{rel_str}"
        except Exception:
            return f"{pwd}"


class WorkerLogPanel:
    """Display worker logs by tailing stdout/stderr from Process."""

    def __init__(self, title: str, empty_message: str, running_message: str, max_lines: int = 8):
        self.title = title
        self.empty_message = empty_message
        self.running_message = running_message
        self.log_lines: deque = deque(maxlen=max_lines * 2)  # Allow more buffer
        self.max_lines = max_lines
        self.last_stdout_pos = 0  # Track file position for efficient tailing
        self.last_stderr_pos = 0
        self.last_process_running = False

    def update_from_process(self, process: Any):
        """Update logs by tailing the Process stdout/stderr files."""
        if not process:
            self.last_process_running = False
            return

        # Use Process tail helpers for consistency
        try:
            self.last_process_running = bool(getattr(process, 'is_running', False))
            stdout_lines = list(process.tail_stdout(lines=self.max_lines, follow=False))
            stderr_lines = list(process.tail_stderr(lines=self.max_lines, follow=False))
        except Exception:
            return

        self.log_lines.clear()

        # Preserve ordering by showing stdout then stderr
        for line in stdout_lines:
            if line:
                self.log_lines.append(('stdout', line))
        for line in stderr_lines:
            if line:
                self.log_lines.append(('stderr', line))

    def __rich__(self) -> Panel:
        if not self.log_lines:
            message = self.running_message if self.last_process_running else self.empty_message
            content = Text(message, style="grey53", justify="center")
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
            title=f"[bold cyan]{self.title}",
            border_style="cyan",
            box=box.HORIZONTALS,
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
            box=box.HORIZONTALS,
        )


class CrawlQueueTreePanel:
    """Display crawl queue with snapshots + hook summary in a tree view."""

    def __init__(self, max_crawls: int = 8, max_snapshots: int = 16):
        self.crawls: list[dict[str, Any]] = []
        self.max_crawls = max_crawls
        self.max_snapshots = max_snapshots

    def update_crawls(self, crawls: list[dict[str, Any]]) -> None:
        """Update crawl tree data."""
        self.crawls = crawls[:self.max_crawls]

    def __rich__(self) -> Panel:
        if not self.crawls:
            content = Text("No active crawls", style="grey53", justify="center")
        else:
            trees = []
            for crawl in self.crawls:
                crawl_status = crawl.get('status', '')
                crawl_label = crawl.get('label', '')
                crawl_id = crawl.get('id', '')[:8]
                crawl_text = Text(f"{self._status_icon(crawl_status)} {crawl_id} {crawl_label}", style="white")
                crawl_tree = Tree(crawl_text, guide_style="grey53")

                snapshots = crawl.get('snapshots', [])[:self.max_snapshots]
                for snap in snapshots:
                    snap_status = snap.get('status', '')
                    snap_label = snap.get('label', '')
                    snap_text = Text(f"{self._status_icon(snap_status)} {snap_label}", style="white")
                    snap_node = crawl_tree.add(snap_text)

                    hooks = snap.get('hooks', {})
                    if hooks:
                        completed = hooks.get('completed', 0)
                        running = hooks.get('running', 0)
                        pending = hooks.get('pending', 0)
                        summary = f"✅ {completed} | ▶️  {running} | ⌛️ {pending}"
                        snap_node.add(Text(summary, style="grey53"))
                trees.append(crawl_tree)
            content = Group(*trees)

        return Panel(
            content,
            title="[bold white]Crawl Queue",
            border_style="white",
            box=box.HORIZONTALS,
        )

    @staticmethod
    def _status_icon(status: str) -> str:
        if status in ('queued', 'pending'):
            return '⏳'
        if status in ('started', 'running'):
            return '▶'
        if status in ('sealed', 'done', 'completed'):
            return '✅'
        if status in ('failed', 'error'):
            return '✖'
        return '•'


class ArchiveBoxProgressLayout:
    """
    Main layout manager for ArchiveBox orchestrator progress display.

    Layout structure:
        ┌─────────────────────────────────────────────────────────────┐
        │              Crawl Queue (full width)                       │
        ├─────────────────────────────────────────────────────────────┤
        │           Running Process Logs (dynamic panels)             │
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

        self.process_panels: List[ProcessLogPanel] = []
        self.orchestrator_log = OrchestratorLogPanel(max_events=8)
        self.crawl_queue_tree = CrawlQueueTreePanel(max_crawls=8, max_snapshots=16)

        # Create layout
        self.layout = self._make_layout()

    def _make_layout(self) -> Layout:
        """Define the layout structure."""
        layout = Layout(name="root")

        # Top-level split: crawl_queue, workers, bottom
        layout.split(
            Layout(name="crawl_queue", size=3),
            Layout(name="processes", ratio=1),
            Layout(name="bottom", size=12),
        )

        # Assign components to layout sections
        layout["crawl_queue"].update(self.crawl_queue)
        layout["processes"].update(Columns([]))
        layout["bottom"].split_row(
            Layout(name="orchestrator_logs", ratio=2),
            Layout(name="crawl_tree", ratio=1),
        )
        layout["orchestrator_logs"].update(self.orchestrator_log)
        layout["crawl_tree"].update(self.crawl_queue_tree)

        return layout

    def update_orchestrator_status(
        self,
        status: str,
        crawl_queue_count: int = 0,
        crawl_workers_count: int = 0,
        binary_queue_count: int = 0,
        binary_workers_count: int = 0,
        max_crawl_workers: int = 8,
    ):
        """Update orchestrator status in the crawl queue panel."""
        self.crawl_queue.orchestrator_status = status
        self.crawl_queue.crawl_queue_count = crawl_queue_count
        self.crawl_queue.crawl_workers_count = crawl_workers_count
        self.crawl_queue.binary_queue_count = binary_queue_count
        self.crawl_queue.binary_workers_count = binary_workers_count
        self.crawl_queue.max_crawl_workers = max_crawl_workers

    def update_process_panels(self, processes: List[Any], pending: Optional[List[Any]] = None) -> None:
        """Update process panels to show all running processes."""
        panels = []
        all_processes = list(processes) + list(pending or [])
        for process in all_processes:
            is_hook = getattr(process, 'process_type', '') == 'hook'
            is_bg = False
            if is_hook:
                try:
                    cmd = getattr(process, 'cmd', [])
                    hook_path = Path(cmd[1]) if len(cmd) > 1 else None
                    hook_name = hook_path.name if hook_path else ''
                    is_bg = '.bg.' in hook_name
                except Exception:
                    is_bg = False
            is_pending = getattr(process, 'status', '') in ('queued', 'pending', 'backoff') or (is_hook and not getattr(process, 'pid', None))
            max_lines = 2 if is_pending else (4 if is_bg else 7)
            panels.append(ProcessLogPanel(process, max_lines=max_lines, compact=is_bg))
        if not panels:
            self.layout["processes"].size = 0
            self.layout["processes"].update(Text(""))
            return

        self.layout["processes"].size = None
        self.layout["processes"].ratio = 1
        self.layout["processes"].update(Columns(panels, equal=True, expand=True))

    def update_crawl_tree(self, crawls: list[dict[str, Any]]) -> None:
        """Update the crawl queue tree panel."""
        self.crawl_queue_tree.update_crawls(crawls)

    def log_event(self, message: str, style: str = "white") -> None:
        """Add an event to the orchestrator log."""
        self.orchestrator_log.add_event(message, style)

    def get_layout(self) -> Layout:
        """Get the Rich Layout object for rendering."""
        return self.layout
