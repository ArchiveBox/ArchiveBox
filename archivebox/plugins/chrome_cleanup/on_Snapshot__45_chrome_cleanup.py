#!/usr/bin/env python3
"""
Clean up Chrome browser session started by chrome_session extractor.

This extractor runs after all Chrome-based extractors (screenshot, pdf, dom)
to terminate the Chrome process and clean up any leftover files.

Usage: on_Snapshot__24_chrome_cleanup.py --url=<url> --snapshot-id=<uuid>
Output: Terminates Chrome process and removes lock files

Environment variables:
    CHROME_USER_DATA_DIR: Chrome profile directory (for lock file cleanup)
    CHROME_PROFILE_NAME: Chrome profile name (default: Default)
"""

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'chrome_cleanup'
CHROME_SESSION_DIR = 'chrome_session'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def cleanup_chrome_session() -> tuple[bool, str | None, str]:
    """
    Clean up Chrome session started by chrome_session extractor.

    Returns: (success, output_info, error_message)
    """
    session_dir = Path(CHROME_SESSION_DIR)

    if not session_dir.exists():
        return True, 'No chrome_session directory found', ''

    pid_file = session_dir / 'pid.txt'
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
