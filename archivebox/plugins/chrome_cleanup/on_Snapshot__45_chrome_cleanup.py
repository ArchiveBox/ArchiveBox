#!/usr/bin/env python3
"""
Clean up Chrome browser session started by chrome_session extractor.

This extractor runs after all Chrome-based extractors (screenshot, pdf, dom)
to clean up the Chrome session. For shared sessions (crawl-level Chrome), it
closes only this snapshot's tab. For standalone sessions, it kills Chrome.

Usage: on_Snapshot__45_chrome_cleanup.py --url=<url> --snapshot-id=<uuid>
Output: Closes tab or terminates Chrome process

Environment variables:
    CHROME_USER_DATA_DIR: Chrome profile directory (for lock file cleanup)
    CHROME_PROFILE_NAME: Chrome profile name (default: Default)
"""

import json
import os
import signal
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'chrome_cleanup'
CHROME_SESSION_DIR = '../chrome_session'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def close_tab_via_cdp(cdp_url: str, page_id: str) -> bool:
    """
    Close a specific tab via Chrome DevTools Protocol.

    Returns True if tab was closed successfully.
    """
    try:
        # Extract port from WebSocket URL (ws://127.0.0.1:PORT/...)
        import re
        match = re.search(r':(\d+)/', cdp_url)
        if not match:
            return False
        port = match.group(1)

        # Use CDP HTTP endpoint to close the target
        close_url = f'http://127.0.0.1:{port}/json/close/{page_id}'
        req = urllib.request.Request(close_url, method='GET')

        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200

    except Exception as e:
        print(f'Failed to close tab via CDP: {e}', file=sys.stderr)
        return False


def kill_listener_processes() -> list[str]:
    """
    Kill any daemonized listener processes (consolelog, ssl, responses, etc.).

    These hooks write listener.pid files that we need to kill.
    Returns list of killed process descriptions.
    """
    killed = []
    snapshot_dir = Path('.').resolve().parent  # Go up from chrome_cleanup dir

    # Look for listener.pid files in sibling directories
    for extractor_dir in snapshot_dir.iterdir():
        if not extractor_dir.is_dir():
            continue

        pid_file = extractor_dir / 'listener.pid'
        if not pid_file.exists():
            continue

        try:
            pid = int(pid_file.read_text().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                # Brief wait for graceful shutdown
                for _ in range(5):
                    try:
                        os.kill(pid, 0)
                        time.sleep(0.05)
                    except OSError:
                        break
                else:
                    # Force kill if still running
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass

                killed.append(f'{extractor_dir.name} listener (PID {pid})')
            except OSError as e:
                if e.errno != 3:  # Not "No such process"
                    killed.append(f'{extractor_dir.name} listener (already dead)')
        except (ValueError, FileNotFoundError):
            pass

    return killed


def cleanup_chrome_session() -> tuple[bool, str | None, str]:
    """
    Clean up Chrome session started by chrome_session extractor.

    For shared sessions (crawl-level Chrome), closes only this snapshot's tab.
    For standalone sessions, kills the Chrome process.

    Returns: (success, output_info, error_message)
    """
    # First, kill any daemonized listener processes
    killed = kill_listener_processes()
    if killed:
        print(f'Killed listener processes: {", ".join(killed)}')

    session_dir = Path(CHROME_SESSION_DIR)

    if not session_dir.exists():
        return True, 'No chrome_session directory found', ''

    # Check if this is a shared session
    shared_file = session_dir / 'shared_session.txt'
    is_shared = False
    if shared_file.exists():
        is_shared = shared_file.read_text().strip().lower() == 'true'

    pid_file = session_dir / 'pid.txt'
    cdp_file = session_dir / 'cdp_url.txt'
    page_id_file = session_dir / 'page_id.txt'

    if is_shared:
        # Shared session - only close this snapshot's tab
        if cdp_file.exists() and page_id_file.exists():
            try:
                cdp_url = cdp_file.read_text().strip()
                page_id = page_id_file.read_text().strip()

                if close_tab_via_cdp(cdp_url, page_id):
                    return True, f'Closed tab {page_id[:8]}... (shared Chrome session)', ''
                else:
                    return True, f'Tab may already be closed (shared Chrome session)', ''

            except Exception as e:
                return True, f'Tab cleanup attempted: {e}', ''

        return True, 'Shared session - Chrome stays running', ''

    # Standalone session - kill the Chrome process
    killed = False

    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())

            # Try graceful termination first
            try:
                os.kill(pid, signal.SIGTERM)
                killed = True

                # Wait briefly for graceful shutdown
                for _ in range(10):
                    try:
                        os.kill(pid, 0)  # Check if still running
                        time.sleep(0.1)
                    except OSError:
                        break  # Process is gone
                else:
                    # Force kill if still running
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass

            except OSError as e:
                # Process might already be dead, that's fine
                if e.errno == 3:  # No such process
                    pass
                else:
                    return False, None, f'Failed to kill Chrome PID {pid}: {e}'

        except ValueError:
            return False, None, f'Invalid PID in {pid_file}'
        except Exception as e:
            return False, None, f'{type(e).__name__}: {e}'

    # Clean up Chrome profile lock files if configured
    user_data_dir = get_env('CHROME_USER_DATA_DIR', '')
    profile_name = get_env('CHROME_PROFILE_NAME', 'Default')

    if user_data_dir:
        user_data_path = Path(user_data_dir)
        for lockfile in [
            user_data_path / 'SingletonLock',
            user_data_path / profile_name / 'SingletonLock',
        ]:
            try:
                lockfile.unlink(missing_ok=True)
            except Exception:
                pass  # Best effort cleanup

    result_info = f'Chrome cleanup: PID {"killed" if killed else "not found"}'
    return True, result_info, ''


@click.command()
@click.option('--url', required=True, help='URL that was loaded')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Clean up Chrome browser session."""

    start_ts = datetime.now(timezone.utc)
    output = None
    status = 'failed'
    error = ''

    try:
        success, output, error = cleanup_chrome_session()
        status = 'succeeded' if success else 'failed'

        if success:
            print(f'Chrome cleanup completed: {output}')

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    # Print results
    end_ts = datetime.now(timezone.utc)
    duration = (end_ts - start_ts).total_seconds()

    print(f'START_TS={start_ts.isoformat()}')
    print(f'END_TS={end_ts.isoformat()}')
    print(f'DURATION={duration:.2f}')
    if output:
        print(f'OUTPUT={output}')
    print(f'STATUS={status}')

    if error:
        print(f'ERROR={error}', file=sys.stderr)

    # Print JSON result
    result_json = {
        'extractor': EXTRACTOR_NAME,
        'url': url,
        'snapshot_id': snapshot_id,
        'status': status,
        'start_ts': start_ts.isoformat(),
        'end_ts': end_ts.isoformat(),
        'duration': round(duration, 2),
        'output': output,
        'error': error or None,
    }
    print(f'RESULT_JSON={json.dumps(result_json)}')

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
