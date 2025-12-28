"""
Process validation using psutil and filesystem mtime.

Uses mtime as a "password": PID files are timestamped with process start time.
Since filesystem mtimes can be set arbitrarily but process start times cannot,
comparing them detects PID reuse.
"""

__package__ = 'archivebox.misc'

import os
import time
from pathlib import Path
from typing import Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


def validate_pid_file(pid_file: Path, cmd_file: Optional[Path] = None, tolerance: float = 5.0) -> bool:
    """Validate PID using mtime and optional cmd.sh. Returns True if process is ours."""
    if not PSUTIL_AVAILABLE or not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
        proc = psutil.Process(pid)

        # Check mtime matches process start time
        if abs(pid_file.stat().st_mtime - proc.create_time()) > tolerance:
            return False  # PID reused

        # Validate command if provided
        if cmd_file and cmd_file.exists():
            cmd = cmd_file.read_text()
            cmdline = ' '.join(proc.cmdline())
            if '--remote-debugging-port' in cmd and '--remote-debugging-port' not in cmdline:
                return False
            if ('chrome' in cmd.lower() or 'chromium' in cmd.lower()):
                if 'chrome' not in proc.name().lower() and 'chromium' not in proc.name().lower():
                    return False

        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ValueError, OSError):
        return False


def write_pid_file_with_mtime(pid_file: Path, pid: int, start_time: float):
    """Write PID file and set mtime to process start time."""
    pid_file.write_text(str(pid))
    try:
        os.utime(pid_file, (start_time, start_time))
    except OSError:
        pass  # mtime optional, validation degrades gracefully


def write_cmd_file(cmd_file: Path, cmd: list[str]):
    """Write shell command script."""
    def escape(arg: str) -> str:
        return f'"{arg.replace(chr(34), chr(92)+chr(34))}"' if any(c in arg for c in ' "$') else arg

    script = '#!/bin/bash\n' + ' '.join(escape(arg) for arg in cmd) + '\n'
    cmd_file.write_text(script)
    try:
        cmd_file.chmod(0o755)
    except OSError:
        pass


def safe_kill_process(pid_file: Path, cmd_file: Optional[Path] = None, signal_num: int = 15) -> bool:
    """Kill process after validation. Returns True if killed."""
    if not validate_pid_file(pid_file, cmd_file):
        pid_file.unlink(missing_ok=True)  # Clean stale file
        return False

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal_num)
        return True
    except (OSError, ValueError, ProcessLookupError):
        return False
