#!/usr/bin/env python3
"""
Clean up Chrome browser session at the end of a crawl.

This runs after all snapshots in a crawl have been processed to terminate
the shared Chrome session that was started by on_Crawl__10_chrome_session.js.

Usage: on_Crawl__99_chrome_cleanup.py --crawl-id=<uuid>
Output: Terminates the crawl's Chrome process
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


def cleanup_crawl_chrome() -> tuple[bool, str | None, str]:
    """
    Clean up Chrome session for the crawl.

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
                print(f'[*] Sent SIGTERM to Chrome PID {pid}')

                # Wait briefly for graceful shutdown
                for _ in range(20):
                    try:
                        os.kill(pid, 0)  # Check if still running
                        time.sleep(0.1)
                    except OSError:
                        print(f'[+] Chrome process {pid} terminated')
                        break  # Process is gone
                else:
                    # Force kill if still running
                    print(f'[!] Chrome still running, sending SIGKILL')
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass

            except OSError as e:
                # Process might already be dead, that's fine
                if e.errno == 3:  # No such process
                    print(f'[*] Chrome process {pid} already terminated')
                else:
                    return False, None, f'Failed to kill Chrome PID {pid}: {e}'

        except ValueError:
            return False, None, f'Invalid PID in {pid_file}'
        except Exception as e:
            return False, None, f'{type(e).__name__}: {e}'

    result_info = f'Crawl Chrome cleanup: PID {"killed" if killed else "not found or already terminated"}'
    return True, result_info, ''


@click.command()
@click.option('--crawl-id', required=True, help='Crawl UUID')
@click.option('--source-url', default='', help='Source URL (unused)')
def main(crawl_id: str, source_url: str):
    """Clean up shared Chrome browser session for crawl."""

    start_ts = datetime.now(timezone.utc)
    output = None
    status = 'failed'
    error = ''

    try:
        success, output, error = cleanup_crawl_chrome()
        status = 'succeeded' if success else 'failed'

        if success:
            print(f'Crawl Chrome cleanup completed: {output}')

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
        'crawl_id': crawl_id,
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
