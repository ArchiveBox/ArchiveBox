"""
PID file utilities for tracking worker and orchestrator processes.

PID files are stored in data/tmp/workers/ and contain:
- Line 1: PID
- Line 2: Worker type (orchestrator, crawl, snapshot, archiveresult)
- Line 3: Extractor filter (optional, for archiveresult workers)
- Line 4: Started at ISO timestamp
"""

__package__ = 'archivebox.workers'

import os
import signal
from pathlib import Path
from datetime import datetime, timezone

from django.conf import settings


def get_pid_dir() -> Path:
    """Get the directory for PID files, creating it if needed."""
    pid_dir = Path(settings.DATA_DIR) / 'tmp' / 'workers'
    pid_dir.mkdir(parents=True, exist_ok=True)
    return pid_dir


def write_pid_file(worker_type: str, worker_id: int = 0, extractor: str | None = None) -> Path:
    """
    Write a PID file for the current process.
    Returns the path to the PID file.
    """
    pid_dir = get_pid_dir()
    
    if worker_type == 'orchestrator':
        pid_file = pid_dir / 'orchestrator.pid'
    else:
        pid_file = pid_dir / f'{worker_type}_worker_{worker_id}.pid'
    
    content = f"{os.getpid()}\n{worker_type}\n{extractor or ''}\n{datetime.now(timezone.utc).isoformat()}\n"
    pid_file.write_text(content)
    
    return pid_file


def read_pid_file(path: Path) -> dict | None:
    """
    Read and parse a PID file.
    Returns dict with pid, worker_type, extractor, started_at or None if invalid.
    """
    try:
        if not path.exists():
            return None
        
        lines = path.read_text().strip().split('\n')
        if len(lines) < 4:
            return None
        
        return {
            'pid': int(lines[0]),
            'worker_type': lines[1],
            'extractor': lines[2] or None,
            'started_at': datetime.fromisoformat(lines[3]),
            'pid_file': path,
        }
    except (ValueError, IndexError, OSError):
        return None


def remove_pid_file(path: Path) -> None:
    """Remove a PID file if it exists."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks
        return True
    except (OSError, ProcessLookupError):
        return False


def get_all_pid_files() -> list[Path]:
    """Get all PID files in the workers directory."""
    pid_dir = get_pid_dir()
    return list(pid_dir.glob('*.pid'))


def get_all_worker_pids(worker_type: str | None = None) -> list[dict]:
    """
    Get info about all running workers.
    Optionally filter by worker_type.
    """
    workers = []
    
    for pid_file in get_all_pid_files():
        info = read_pid_file(pid_file)
        if info is None:
            continue
        
        # Skip if process is dead
        if not is_process_alive(info['pid']):
            continue
        
        # Filter by type if specified
        if worker_type and info['worker_type'] != worker_type:
            continue
        
        workers.append(info)
    
    return workers


def cleanup_stale_pid_files() -> int:
    """
    Remove PID files for processes that are no longer running.
    Returns the number of stale files removed.
    """
    removed = 0
    
    for pid_file in get_all_pid_files():
        info = read_pid_file(pid_file)
        if info is None:
            # Invalid PID file, remove it
            remove_pid_file(pid_file)
            removed += 1
            continue
        
        if not is_process_alive(info['pid']):
            remove_pid_file(pid_file)
            removed += 1
    
    return removed


def get_running_worker_count(worker_type: str) -> int:
    """Get the count of running workers of a specific type."""
    return len(get_all_worker_pids(worker_type))


def get_next_worker_id(worker_type: str) -> int:
    """Get the next available worker ID for a given type."""
    existing_ids = set()
    
    for pid_file in get_all_pid_files():
        # Parse worker ID from filename like "snapshot_worker_3.pid"
        name = pid_file.stem
        if name.startswith(f'{worker_type}_worker_'):
            try:
                worker_id = int(name.split('_')[-1])
                existing_ids.add(worker_id)
            except ValueError:
                continue
    
    # Find the lowest unused ID
    next_id = 0
    while next_id in existing_ids:
        next_id += 1
    
    return next_id


def stop_worker(pid: int, graceful: bool = True) -> bool:
    """
    Stop a worker process.
    If graceful=True, sends SIGTERM first, then SIGKILL after timeout.
    Returns True if process was stopped.
    """
    if not is_process_alive(pid):
        return True
    
    try:
        if graceful:
            os.kill(pid, signal.SIGTERM)
            # Give it a moment to shut down
            import time
            for _ in range(10):  # Wait up to 1 second
                time.sleep(0.1)
                if not is_process_alive(pid):
                    return True
            # Force kill if still running
            os.kill(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
        return True
    except (OSError, ProcessLookupError):
        return True  # Process already dead
