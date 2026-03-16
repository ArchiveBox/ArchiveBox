"""
Rich Layout-based live progress display for ArchiveBox orchestrator.

Shows a comprehensive dashboard with:
- Top: Crawl queue status (full width)
- Middle: Crawl queue tree with hook outputs
- Bottom: Running process logs (dynamic panels)
"""

__package__ = 'archivebox.misc'

from datetime import datetime, timezone
import os
import re
from typing import List, Optional, Any
from collections import deque
from pathlib import Path

from rich import box
from rich.console import Group
from rich.layout import Layout
from rich.columns import Columns
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.tree import Tree
from rich.cells import cell_len

from archivebox.config import VERSION


_RICH_TAG_RE = re.compile(r'\[/?[^\]]+\]')


def _strip_rich(text: str) -> str:
    return _RICH_TAG_RE.sub('', text or '').strip()


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

    def __init__(self, process: Any, max_lines: int = 8, compact: bool | None = None, bg_terminating: bool = False):
        self.process = process
        self.max_lines = max_lines
        self.compact = compact
        self.bg_terminating = bg_terminating

    def __rich__(self) -> Panel:
        completed_line = self._completed_output_line()
        if completed_line:
            style = "green" if self._completed_ok() else "yellow"
            return Text(completed_line, style=style)

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
        border_style = self._border_style(is_pending=is_pending)
        height = 2 if is_pending else None
        return Panel(
            content,
            title=title,
            border_style=border_style,
            box=box.HORIZONTALS,
            padding=(0, 1),
            height=height,
        )

    def plain_lines(self) -> list[str]:
        completed_line = self._completed_output_line()
        if completed_line:
            return [completed_line]

        lines = []
        if not self._is_pending():
            output_line = self._output_line()
            if output_line:
                lines.append(output_line)

        try:
            stdout_lines = list(self.process.tail_stdout(lines=self.max_lines, follow=False))
            stderr_lines = list(self.process.tail_stderr(lines=self.max_lines, follow=False))
        except Exception:
            stdout_lines = []
            stderr_lines = []

        for line in stdout_lines:
            if line:
                lines.append(line)
        for line in stderr_lines:
            if line:
                lines.append(line)
        return lines

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

    def _completed_ok(self) -> bool:
        exit_code = getattr(self.process, 'exit_code', None)
        return exit_code in (0, None)

    def _completed_output_line(self) -> str:
        status = getattr(self.process, 'status', '')
        if status != 'exited':
            return ''
        output_line = self._output_line()
        if not output_line:
            return ''
        if not self._has_output_files():
            return ''
        return output_line

    def _has_output_files(self) -> bool:
        pwd = getattr(self.process, 'pwd', None)
        if not pwd:
            return False
        try:
            base = Path(pwd)
            if not base.exists():
                return False
            ignore = {'stdout.log', 'stderr.log', 'cmd.sh', 'process.pid', 'hook.pid', 'listener.pid'}
            for path in base.rglob('*'):
                if path.is_file() and path.name not in ignore:
                    return True
        except Exception:
            return False
        return False

    def _border_style(self, is_pending: bool) -> str:
        if is_pending:
            return "grey53"
        status = getattr(self.process, 'status', '')
        if status == 'exited':
            exit_code = getattr(self.process, 'exit_code', None)
            return "green" if exit_code in (0, None) else "yellow"
        is_hook = getattr(self.process, 'process_type', '') == 'hook'
        if is_hook and not self._is_background_hook():
            return "green"
        if is_hook and self._is_background_hook() and self.bg_terminating:
            return "red"
        return "cyan"

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

                    output_path = snap.get('output_path', '')
                    if output_path:
                        snap_node.add(Text(output_path, style="grey53"))

                    hooks = snap.get('hooks', []) or []
                    for hook in hooks:
                        status = hook.get('status', '')
                        path = hook.get('path', '')
                        size = hook.get('size', '')
                        elapsed = hook.get('elapsed', '')
                        timeout = hook.get('timeout', '')
                        is_bg = hook.get('is_bg', False)
                        is_running = hook.get('is_running', False)
                        is_pending = hook.get('is_pending', False)
                        icon, color = self._hook_style(status, is_bg=is_bg, is_running=is_running, is_pending=is_pending)
                        stats = self._hook_stats(size=size, elapsed=elapsed, timeout=timeout, status=status)
                        line = Text(f"{icon} {path}{stats}", style=color)
                        stderr_tail = hook.get('stderr', '')
                        if stderr_tail:
                            left_str = f"{icon} {path}{stats}"
                            avail = self._available_width(left_str, indent=16)
                            trunc = getattr(self, "_truncate_tail", self._truncate_to_width)
                            stderr_tail = trunc(stderr_tail, avail)
                            if not stderr_tail:
                                snap_node.add(line)
                                continue
                            row = Table.grid(expand=True)
                            row.add_column(justify="left", ratio=1)
                            row.add_column(justify="right")
                            row.add_row(line, Text(stderr_tail, style="grey70"))
                            snap_node.add(row)
                        else:
                            snap_node.add(line)
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

    @staticmethod
    def _hook_style(status: str, is_bg: bool = False, is_running: bool = False, is_pending: bool = False) -> tuple[str, str]:
        if status == 'succeeded':
            return '✅', 'green'
        if status == 'failed':
            return '✖', 'red'
        if status == 'skipped':
            return '⏭', 'grey53'
        if is_pending:
            return '⌛️', 'grey53'
        if is_running and is_bg:
            return '᠁', 'cyan'
        if is_running:
            return '▶️', 'cyan'
        if status == 'started':
            return '▶️', 'cyan'
        return '•', 'grey53'

    @staticmethod
    def _hook_stats(size: str = '', elapsed: str = '', timeout: str = '', status: str = '') -> str:
        if status in ('succeeded', 'failed', 'skipped'):
            parts = []
            if size:
                parts.append(size)
            if elapsed:
                parts.append(elapsed)
            if not parts:
                return ''
            return f" ({' | '.join(parts)})"
        if elapsed or timeout:
            size_part = '...' if elapsed or timeout else ''
            time_part = ''
            if elapsed and timeout:
                time_part = f"{elapsed}/{timeout}"
            elif elapsed:
                time_part = f"{elapsed}"
            return f" ({size_part} | {time_part})" if time_part else f" ({size_part})"
        return ''

    @staticmethod
    def _terminal_width() -> int:
        try:
            return os.get_terminal_size().columns
        except OSError:
            return 120

    @staticmethod
    def _truncate_to_width(text: str, max_width: int) -> str:
        if not text or max_width <= 0:
            return ''
        t = Text(text)
        t.truncate(max_width, overflow="ellipsis")
        return t.plain

    @staticmethod
    def _truncate_tail(text: str, max_width: int) -> str:
        if not text or max_width <= 0:
            return ''
        if cell_len(text) <= max_width:
            return text
        if max_width <= 1:
            return '…'
        return f"…{text[-(max_width - 1):]}"

    def _available_width(self, left_text: str, indent: int = 0) -> int:
        width = self._terminal_width()
        base = max(0, width - cell_len(left_text) - indent - 6)
        cap = max(0, (width * 2) // 5)
        return max(0, min(base, cap))


class ArchiveBoxProgressLayout:
    """
    Main layout manager for ArchiveBox orchestrator progress display.

    Layout structure:
        ┌─────────────────────────────────────────────────────────────┐
        │              Crawl Queue (full width)                       │
        ├─────────────────────────────────────────────────────────────┤
        │           Crawl Queue Tree (hooks + outputs)                │
        ├─────────────────────────────────────────────────────────────┤
        │           Running Process Logs (dynamic panels)             │
        └─────────────────────────────────────────────────────────────┘
    """

    def __init__(self, crawl_id: Optional[str] = None):
        self.crawl_id = crawl_id
        self.start_time = datetime.now(timezone.utc)

        # Create components
        self.crawl_queue = CrawlQueuePanel()
        self.crawl_queue.crawl_id = crawl_id

        self.process_panels: List[ProcessLogPanel] = []
        self.crawl_queue_tree = CrawlQueueTreePanel(max_crawls=8, max_snapshots=16)

        # Create layout
        self.layout = self._make_layout()

    def _make_layout(self) -> Layout:
        """Define the layout structure."""
        layout = Layout(name="root")

        # Top-level split: crawl_queue, crawl_tree, processes
        layout.split(
            Layout(name="crawl_queue", size=3),
            Layout(name="crawl_tree", size=20),
            Layout(name="processes", ratio=1),
        )

        # Assign components to layout sections
        layout["crawl_queue"].update(self.crawl_queue)
        layout["crawl_tree"].update(self.crawl_queue_tree)
        layout["processes"].update(Columns([]))

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
        fg_running = False
        for process in processes:
            if getattr(process, 'process_type', '') != 'hook':
                continue
            try:
                cmd = getattr(process, 'cmd', [])
                hook_path = Path(cmd[1]) if len(cmd) > 1 else None
                hook_name = hook_path.name if hook_path else ''
                if '.bg.' in hook_name:
                    continue
                if '.bg.' not in hook_name:
                    fg_running = True
                    break
            except Exception:
                continue
        fg_pending = False
        for process in (pending or []):
            if getattr(process, 'process_type', '') != 'hook':
                continue
            try:
                cmd = getattr(process, 'cmd', [])
                hook_path = Path(cmd[1]) if len(cmd) > 1 else None
                hook_name = hook_path.name if hook_path else ''
                if '.bg.' in hook_name:
                    continue
                if '.bg.' not in hook_name:
                    fg_pending = True
                    break
            except Exception:
                continue
        bg_terminating = bool(processes) and not fg_running and not fg_pending
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
            if is_hook and is_bg:
                continue
            if not self._has_log_lines(process):
                continue
            is_pending = getattr(process, 'status', '') in ('queued', 'pending', 'backoff') or (is_hook and not getattr(process, 'pid', None))
            max_lines = 2 if is_pending else (4 if is_bg else 7)
            panels.append(ProcessLogPanel(process, max_lines=max_lines, compact=is_bg, bg_terminating=bg_terminating))
        if not panels:
            self.layout["processes"].size = 0
            self.layout["processes"].update(Text(""))
            self.process_panels = []
            return

        self.process_panels = panels
        self.layout["processes"].size = None
        self.layout["processes"].ratio = 1
        self.layout["processes"].update(Columns(panels, equal=True, expand=True))

    def update_crawl_tree(self, crawls: list[dict[str, Any]]) -> None:
        """Update the crawl queue tree panel."""
        self.crawl_queue_tree.update_crawls(crawls)
        # Auto-size crawl tree panel to content
        line_count = 0
        for crawl in crawls:
            line_count += 1
            for snap in crawl.get('snapshots', []) or []:
                line_count += 1
                if snap.get('output_path'):
                    line_count += 1
                for _ in snap.get('hooks', []) or []:
                    line_count += 1
        self.layout["crawl_tree"].size = max(4, line_count + 2)

    def log_event(self, message: str, style: str = "white") -> None:
        """Add an event to the orchestrator log."""
        return

    def get_layout(self) -> Layout:
        """Get the Rich Layout object for rendering."""
        return self.layout

    def plain_lines(self) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        queue = self.crawl_queue
        queue_line = (
            f"Status: {queue.orchestrator_status} | Crawls: {queue.crawl_queue_count} queued | "
            f"Binaries: {queue.binary_queue_count} queued | Workers: {queue.crawl_workers_count}/{queue.max_crawl_workers} "
            f"crawl, {queue.binary_workers_count} binary"
        )
        lines.append(("crawl_queue", queue_line))

        for panel in self.process_panels:
            title = _strip_rich(panel._title())
            for line in panel.plain_lines():
                if line:
                    lines.append((title or "process", line))

        for crawl in self.crawl_queue_tree.crawls:
            crawl_line = f"{self.crawl_queue_tree._status_icon(crawl.get('status', ''))} {crawl.get('id', '')[:8]} {crawl.get('label', '')}".strip()
            lines.append(("crawl_tree", crawl_line))
            for snap in crawl.get('snapshots', []):
                snap_line = f"  {self.crawl_queue_tree._status_icon(snap.get('status', ''))} {snap.get('label', '')}".rstrip()
                lines.append(("crawl_tree", snap_line))
                output_path = snap.get('output_path', '')
                if output_path:
                    lines.append(("crawl_tree", f"    {output_path}"))
                for hook in snap.get('hooks', []) or []:
                    status = hook.get('status', '')
                    path = hook.get('path', '')
                    icon, _ = self.crawl_queue_tree._hook_style(
                        status,
                        is_bg=hook.get('is_bg', False),
                        is_running=hook.get('is_running', False),
                        is_pending=hook.get('is_pending', False),
                    )
                    stats = self.crawl_queue_tree._hook_stats(
                        size=hook.get('size', ''),
                        elapsed=hook.get('elapsed', ''),
                        timeout=hook.get('timeout', ''),
                        status=status,
                    )
                    stderr_tail = hook.get('stderr', '')
                    hook_line = f"    {icon} {path}{stats}".strip()
                    if stderr_tail:
                        avail = self.crawl_queue_tree._available_width(hook_line, indent=16)
                        trunc = getattr(self.crawl_queue_tree, "_truncate_tail", self.crawl_queue_tree._truncate_to_width)
                        stderr_tail = trunc(stderr_tail, avail)
                        if stderr_tail:
                            hook_line = f"{hook_line}  {stderr_tail}"
                    if hook_line:
                        lines.append(("crawl_tree", hook_line))

        return lines

    @staticmethod
    def _has_log_lines(process: Any) -> bool:
        try:
            stdout_lines = list(process.tail_stdout(lines=1, follow=False))
            if any(line.strip() for line in stdout_lines):
                return True
            stderr_lines = list(process.tail_stderr(lines=1, follow=False))
            if any(line.strip() for line in stderr_lines):
                return True
        except Exception:
            return False
        return False
