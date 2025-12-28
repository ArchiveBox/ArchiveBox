"""
Cross-platform process validation utilities using psutil.

Uses filesystem mtime as a "password" to validate PIDs haven't been reused.
Since filesystem mtimes can be set arbitrarily, but process start times cannot,
we can detect PID reuse by comparing:
  - PID file mtime (set to process start time when we launched it)
  - Actual process start time (from psutil)

If they match (within tolerance), it's our process.
If they don't match, the PID was reused by a different process.
"""

__package__ = 'archivebox.misc'

import os
import time
from pathlib import Path
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None


def get_process_info(pid: int) -> Optional[dict]:
    """
    Get process information using psutil.

    Args:
        pid: Process ID

    Returns:
        Dict with 'start_time', 'cmdline', 'name', 'status' or None if not found
    """
    if psutil is None:
        return None

    try:
        proc = psutil.Process(pid)
        return {
            'start_time': proc.create_time(),  # Unix epoch seconds
            'cmdline': proc.cmdline(),
            'name': proc.name(),
            'status': proc.status(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def validate_pid_file(
    pid_file: Path,
    cmd_file: Optional[Path] = None,
    tolerance_seconds: float = 5.0
) -> bool:
    """
    Validate PID file using mtime as "password".

    Returns True only if ALL checks pass:
    1. PID file exists and contains valid integer
    2. Process with that PID exists
    3. File mtime matches process start time (within tolerance)
    4. If cmd_file provided, process cmdline contains expected args

    Args:
        pid_file: Path to .pid file
        cmd_file: Optional path to cmd.sh for command validation
        tolerance_seconds: Allowed difference between mtime and start time

    Returns:
        True if PID is validated, False if reused/invalid
    """
    if psutil is None:
        # Fallback: just check if process exists (no validation)
        return _validate_pid_file_without_psutil(pid_file)

    # Check PID file exists
    if not pid_file.exists():
        return False

    # Read PID
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return False

    # Get process info
    proc_info = get_process_info(pid)
    if proc_info is None:
        return False  # Process doesn't exist

    # Check mtime matches process start time
    try:
        file_mtime = pid_file.stat().st_mtime
    except OSError:
        return False

    proc_start_time = proc_info['start_time']
    time_diff = abs(file_mtime - proc_start_time)

    if time_diff > tolerance_seconds:
        # PID was reused by different process
        return False

    # Validate command if provided
    if cmd_file and cmd_file.exists():
        try:
            expected_cmd = cmd_file.read_text().strip()
            actual_cmdline = ' '.join(proc_info['cmdline'])

            # Check for key indicators (chrome, debug port, etc.)
            # This is a heuristic - just checks if critical args are present
            if '--remote-debugging-port' in expected_cmd:
                if '--remote-debugging-port' not in actual_cmdline:
                    return False

            if 'chrome' in expected_cmd.lower() or 'chromium' in expected_cmd.lower():
                proc_name_lower = proc_info['name'].lower()
                if 'chrome' not in proc_name_lower and 'chromium' not in proc_name_lower:
                    return False

        except OSError:
            pass  # Can't validate command, but other checks passed

    return True


def _validate_pid_file_without_psutil(pid_file: Path) -> bool:
    """
    Fallback validation when psutil not available.
    Only checks if process exists, no validation.
    """
    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # Signal 0 = check existence
        return True
    except (OSError, ValueError, ProcessLookupError):
        return False


def write_pid_file_with_mtime(pid_file: Path, pid: int, start_time: float):
    """
    Write PID file and set mtime to process start time.

    This creates a "password" that can be validated later to ensure
    the PID hasn't been reused by a different process.

    Args:
        pid_file: Path to .pid file to create
        pid: Process ID to write
        start_time: Process start time as Unix epoch seconds
    """
    pid_file.write_text(str(pid))

    # Set both atime and mtime to process start time
    try:
        os.utime(pid_file, (start_time, start_time))
    except OSError:
        # If we can't set mtime, file is still written
        # Validation will be less reliable but won't break
        pass


def write_cmd_file(cmd_file: Path, cmd: list[str]):
    """
    Write command script for validation.

    Args:
        cmd_file: Path to cmd.sh to create
        cmd: Command list (e.g., ['chrome', '--remote-debugging-port=9222', ...])
    """
    # Shell escape arguments with spaces or special chars
    def shell_escape(arg: str) -> str:
        if ' ' in arg or '"' in arg or "'" in arg or '$' in arg:
            # Escape double quotes and wrap in double quotes
            return f'"{arg.replace(chr(34), chr(92) + chr(34))}"'
        return arg

    escaped_cmd = [shell_escape(arg) for arg in cmd]
    script = '#!/bin/bash\n' + ' '.join(escaped_cmd) + '\n'

    cmd_file.write_text(script)
    try:
        cmd_file.chmod(0o755)
    except OSError:
        pass  # Best effort


def safe_kill_process(
    pid_file: Path,
    cmd_file: Optional[Path] = None,
    signal_num: int = 15,  # SIGTERM
    validate: bool = True
) -> bool:
    """
    Safely kill a process with validation.

    Args:
        pid_file: Path to .pid file
        cmd_file: Optional path to cmd.sh for validation
        signal_num: Signal to send (default SIGTERM=15)
        validate: If True, validate process identity before killing

    Returns:
        True if process was killed, False if not found or validation failed
    """
    if not pid_file.exists():
        return False

    # Validate process identity first
    if validate:
        if not validate_pid_file(pid_file, cmd_file):
            # PID reused by different process, don't kill
            # Clean up stale PID file
            try:
                pid_file.unlink()
            except OSError:
                pass
            return False

    # Read PID and kill
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal_num)
        return True
    except (OSError, ValueError, ProcessLookupError):
        return False


def cleanup_stale_pid_files(directory: Path, cmd_file_name: str = 'cmd.sh') -> int:
    """
    Remove stale PID files from directory.

    A PID file is stale if:
    - Process no longer exists, OR
    - Process exists but validation fails (PID reused)

    Args:
        directory: Directory to scan for *.pid files
        cmd_file_name: Name of command file for validation (default: cmd.sh)

    Returns:
        Number of stale PID files removed
    """
    if not directory.exists():
        return 0

    removed = 0
    for pid_file in directory.glob('**/*.pid'):
        cmd_file = pid_file.parent / cmd_file_name

        # Check if valid
        if not validate_pid_file(pid_file, cmd_file):
            try:
                pid_file.unlink()
                removed += 1
            except OSError:
                pass

    return removed
