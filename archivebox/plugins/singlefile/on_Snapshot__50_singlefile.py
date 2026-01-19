#!/usr/bin/env python3
"""
Archive a URL using SingleFile.

Usage: on_Snapshot__singlefile.py --url=<url> --snapshot-id=<uuid>
Output: Writes singlefile.html to $PWD

Environment variables:
    SINGLEFILE_ENABLED: Enable SingleFile archiving (default: True)
    SINGLEFILE_BINARY: Path to SingleFile binary (default: single-file)
    SINGLEFILE_NODE_BINARY: Path to Node.js binary (x-fallback: NODE_BINARY)
    SINGLEFILE_CHROME_BINARY: Path to Chrome binary (x-fallback: CHROME_BINARY)
    SINGLEFILE_TIMEOUT: Timeout in seconds (x-fallback: TIMEOUT)
    SINGLEFILE_USER_AGENT: User agent string (x-fallback: USER_AGENT)
    SINGLEFILE_COOKIES_FILE: Path to cookies file (x-fallback: COOKIES_FILE)
    SINGLEFILE_CHECK_SSL_VALIDITY: Whether to verify SSL certs (x-fallback: CHECK_SSL_VALIDITY)
    SINGLEFILE_CHROME_ARGS: Chrome command-line arguments (x-fallback: CHROME_ARGS)
    SINGLEFILE_ARGS: Default SingleFile arguments (JSON array)
    SINGLEFILE_ARGS_EXTRA: Extra arguments to append (JSON array)
"""

import json
import os
import subprocess
import sys
import threading
import time
from urllib.request import urlopen
from pathlib import Path
import shutil

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'singlefile'
BIN_NAME = 'single-file'
BIN_PROVIDERS = 'npm,env'
OUTPUT_DIR = '.'
OUTPUT_FILE = 'singlefile.html'
EXTENSION_SAVE_SCRIPT = Path(__file__).parent / 'singlefile_extension_save.js'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_bool(name: str, default: bool = False) -> bool:
    val = get_env(name, '').lower()
    if val in ('true', '1', 'yes', 'on'):
        return True
    if val in ('false', '0', 'no', 'off'):
        return False
    return default


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def get_env_array(name: str, default: list[str] | None = None) -> list[str]:
    """Parse a JSON array from environment variable."""
    val = get_env(name, '')
    if not val:
        return default if default is not None else []
    try:
        result = json.loads(val)
        if isinstance(result, list):
            return [str(item) for item in result]
        return default if default is not None else []
    except json.JSONDecodeError:
        return default if default is not None else []


STATICFILE_DIR = '../staticfile'

def has_staticfile_output() -> bool:
    """Check if staticfile extractor already downloaded this URL."""
    staticfile_dir = Path(STATICFILE_DIR)
    if not staticfile_dir.exists():
        return False
    stdout_log = staticfile_dir / 'stdout.log'
    if not stdout_log.exists():
        return False
    for line in stdout_log.read_text(errors='ignore').splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get('type') == 'ArchiveResult' and record.get('status') == 'succeeded':
            return True
    return False


# Chrome session directory (relative to extractor output dir)
# Note: Chrome binary is obtained via CHROME_BINARY env var, not searched for.
# The centralized Chrome binary search is in chrome_utils.js findChromium().
CHROME_SESSION_DIR = '../chrome'


def get_cdp_url(wait_seconds: float = 0.0) -> str | None:
    """Get CDP URL from chrome plugin if available."""
    cdp_file = Path(CHROME_SESSION_DIR) / 'cdp_url.txt'
    deadline = time.time() + max(wait_seconds, 0.0)
    while True:
        if cdp_file.exists():
            cdp_url = cdp_file.read_text().strip()
            return cdp_url or None
        if time.time() >= deadline:
            return None
        time.sleep(0.2)


def get_port_from_cdp_url(cdp_url: str) -> str | None:
    """Extract port from CDP WebSocket URL (ws://127.0.0.1:PORT/...)."""
    import re
    match = re.search(r':(\d+)/', cdp_url)
    if match:
        return match.group(1)
    return None


def is_cdp_server_available(cdp_remote_url: str) -> bool:
    try:
        with urlopen(f'{cdp_remote_url}/json/version', timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def save_singlefile(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Archive URL using SingleFile.

    If a Chrome session exists (from chrome plugin), connects to it via CDP.
    Otherwise launches a new Chrome instance.

    Returns: (success, output_path, error_message)
    """
    print(f'[singlefile] CLI mode start url={url}', file=sys.stderr)
    # Get config from env (with SINGLEFILE_ prefix, x-fallback handled by config loader)
    timeout = get_env_int('SINGLEFILE_TIMEOUT') or get_env_int('TIMEOUT', 120)
    user_agent = get_env('SINGLEFILE_USER_AGENT') or get_env('USER_AGENT', '')
    check_ssl = get_env_bool('SINGLEFILE_CHECK_SSL_VALIDITY', True) if get_env('SINGLEFILE_CHECK_SSL_VALIDITY') else get_env_bool('CHECK_SSL_VALIDITY', True)
    cookies_file = get_env('SINGLEFILE_COOKIES_FILE') or get_env('COOKIES_FILE', '')
    singlefile_args = get_env_array('SINGLEFILE_ARGS', [])
    singlefile_args_extra = get_env_array('SINGLEFILE_ARGS_EXTRA', [])
    chrome_args = get_env_array('SINGLEFILE_CHROME_ARGS') or get_env_array('CHROME_ARGS', [])
    chrome = get_env('SINGLEFILE_CHROME_BINARY') or get_env('CHROME_BINARY', '')

    cmd = [binary, *singlefile_args]

    # Try to use existing Chrome session via CDP (prefer HTTP base URL)
    cdp_wait = min(10, max(1, timeout // 10))
    cdp_url = get_cdp_url(wait_seconds=cdp_wait)
    cdp_remote_url = None
    if cdp_url:
        if cdp_url.startswith(('http://', 'https://')):
            cdp_remote_url = cdp_url
        else:
            port = get_port_from_cdp_url(cdp_url)
            if port:
                cdp_remote_url = f'http://127.0.0.1:{port}'
            else:
                cdp_remote_url = cdp_url

    if cdp_remote_url and not is_cdp_server_available(cdp_remote_url):
        cdp_remote_url = None

    if cdp_remote_url:
        print(f'[singlefile] Using existing Chrome session: {cdp_remote_url}', file=sys.stderr)
        cmd.extend(['--browser-server', cdp_remote_url])
    elif chrome:
        print(f'[singlefile] Launching Chrome binary: {chrome}', file=sys.stderr)
        cmd.extend(['--browser-executable-path', chrome])

    # Pass Chrome arguments (only when launching a new browser)
    if chrome_args and not cdp_remote_url:
        # SingleFile expects --browser-args as a JSON array string
        cmd.extend(['--browser-args', json.dumps(chrome_args)])

    # SSL handling
    if not check_ssl:
        cmd.append('--browser-ignore-insecure-certs')

    if user_agent:
        cmd.extend(['--user-agent', user_agent])

    if cookies_file and Path(cookies_file).is_file():
        cmd.extend(['--browser-cookies-file', cookies_file])

    # Add extra args from config
    if singlefile_args_extra:
        cmd.extend(singlefile_args_extra)

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)
    output_path = output_dir / OUTPUT_FILE

    cmd.extend([url, str(output_path)])
    print(f'[singlefile] CLI command: {" ".join(cmd[:6])} ...', file=sys.stderr)

    try:
        output_lines: list[str] = []
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        def _read_output() -> None:
            if not process.stdout:
                return
            for line in process.stdout:
                output_lines.append(line)
                sys.stderr.write(line)

        reader = threading.Thread(target=_read_output, daemon=True)
        reader.start()

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            reader.join(timeout=1)
            return False, None, f'Timed out after {timeout} seconds'

        reader.join(timeout=1)
        combined_output = ''.join(output_lines)

        if output_path.exists() and output_path.stat().st_size > 0:
            return True, str(output_path), ''
        else:
            stderr = combined_output
            if 'ERR_NAME_NOT_RESOLVED' in stderr:
                return False, None, 'DNS resolution failed'
            if 'ERR_CONNECTION_REFUSED' in stderr:
                return False, None, 'Connection refused'
            detail = (stderr or '').strip()
            if len(detail) > 2000:
                detail = detail[:2000]
            cmd_preview = list(cmd)
            if '--browser-args' in cmd_preview:
                idx = cmd_preview.index('--browser-args')
                if idx + 1 < len(cmd_preview):
                    cmd_preview[idx + 1] = '<json>'
            cmd_str = ' '.join(cmd_preview)
            return False, None, f'SingleFile failed (cmd={cmd_str}): {detail}'

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


def save_singlefile_with_extension(url: str, timeout: int) -> tuple[bool, str | None, str]:
    """Save using the SingleFile Chrome extension via existing Chrome session."""
    print(f'[singlefile] Extension mode start url={url}', file=sys.stderr)
    # Only attempt if chrome session exists
    cdp_url = get_cdp_url(wait_seconds=min(5, max(1, timeout // 10)))
    if not cdp_url:
        print('[singlefile] No chrome session (cdp_url.txt missing)', file=sys.stderr)
        return False, None, 'No Chrome session available'

    if not EXTENSION_SAVE_SCRIPT.exists():
        print(f'[singlefile] Missing helper script: {EXTENSION_SAVE_SCRIPT}', file=sys.stderr)
        return False, None, 'SingleFile extension helper script missing'

    node_binary = get_env('SINGLEFILE_NODE_BINARY') or get_env('NODE_BINARY', 'node')
    downloads_dir = get_env('CHROME_DOWNLOADS_DIR', '')
    extensions_dir = get_env('CHROME_EXTENSIONS_DIR', '')
    cmd = [node_binary, str(EXTENSION_SAVE_SCRIPT), f'--url={url}']
    print(f'[singlefile] cdp_url={cdp_url}', file=sys.stderr)
    print(f'[singlefile] node={node_binary}', file=sys.stderr)
    node_resolved = shutil.which(node_binary) if node_binary else None
    print(f'[singlefile] node_resolved={node_resolved}', file=sys.stderr)
    print(f'[singlefile] PATH={os.environ.get("PATH","")}', file=sys.stderr)
    if downloads_dir:
        print(f'[singlefile] CHROME_DOWNLOADS_DIR={downloads_dir}', file=sys.stderr)
    if extensions_dir:
        print(f'[singlefile] CHROME_EXTENSIONS_DIR={extensions_dir}', file=sys.stderr)
    print(f'[singlefile] helper_cmd={" ".join(cmd)}', file=sys.stderr)

    try:
        output_lines: list[str] = []
        error_lines: list[str] = []
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        def _read_stream(stream, sink, label: str) -> None:
            if not stream:
                return
            for line in stream:
                sink.append(line)
                sys.stderr.write(line)
                sys.stderr.flush()

        stdout_thread = threading.Thread(target=_read_stream, args=(process.stdout, output_lines, 'stdout'), daemon=True)
        stderr_thread = threading.Thread(target=_read_stream, args=(process.stderr, error_lines, 'stderr'), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            print(f'[singlefile] Extension helper timed out after {timeout}s', file=sys.stderr)
            return False, None, f'Timed out after {timeout} seconds'

        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)

        result_stdout = ''.join(output_lines).encode('utf-8', errors='replace')
        result_stderr = ''.join(error_lines).encode('utf-8', errors='replace')
        result_returncode = process.returncode
    except Exception as e:
        print(f'[singlefile] Extension helper error: {type(e).__name__}: {e}', file=sys.stderr)
        return False, None, f'{type(e).__name__}: {e}'

    print(f'[singlefile] helper_returncode={result_returncode}', file=sys.stderr)
    print(f'[singlefile] helper_stdout_len={len(result_stdout or b"")}', file=sys.stderr)
    print(f'[singlefile] helper_stderr_len={len(result_stderr or b"")}', file=sys.stderr)

    if result_returncode == 0:
        # Prefer explicit stdout path, fallback to local output file
        out_text = result_stdout.decode('utf-8', errors='replace').strip()
        if out_text and Path(out_text).exists():
            print(f'[singlefile] Extension output: {out_text}', file=sys.stderr)
            return True, out_text, ''
        output_path = Path(OUTPUT_DIR) / OUTPUT_FILE
        if output_path.exists() and output_path.stat().st_size > 0:
            print(f'[singlefile] Extension output: {output_path}', file=sys.stderr)
            return True, str(output_path), ''
        return False, None, 'SingleFile extension completed but no output file found'

    stderr = result_stderr.decode('utf-8', errors='replace').strip()
    stdout = result_stdout.decode('utf-8', errors='replace').strip()
    detail = stderr or stdout
    return False, None, detail or 'SingleFile extension failed'


@click.command()
@click.option('--url', required=True, help='URL to archive')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Archive a URL using SingleFile."""

    print(f'[singlefile] Hook starting pid={os.getpid()} url={url}', file=sys.stderr)
    output = None
    status = 'failed'
    error = ''

    try:
        # Check if SingleFile is enabled
        if not get_env_bool('SINGLEFILE_ENABLED', True):
            print('Skipping SingleFile (SINGLEFILE_ENABLED=False)', file=sys.stderr)
            # Feature disabled - no ArchiveResult, just exit
            sys.exit(0)

        # Check if staticfile extractor already handled this (permanent skip)
        if has_staticfile_output():
            print('Skipping SingleFile - staticfile extractor already downloaded this', file=sys.stderr)
            print(json.dumps({'type': 'ArchiveResult', 'status': 'skipped', 'output_str': 'staticfile already exists'}))
            sys.exit(0)

        # Prefer SingleFile extension via existing Chrome session
        timeout = get_env_int('SINGLEFILE_TIMEOUT') or get_env_int('TIMEOUT', 120)
        success, output, error = save_singlefile_with_extension(url, timeout)
        status = 'succeeded' if success else 'failed'

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    if error:
        print(f'ERROR: {error}', file=sys.stderr)

    # Output clean JSONL (no RESULT_JSON= prefix)
    result = {
        'type': 'ArchiveResult',
        'status': status,
        'output_str': output or error or '',
    }
    print(json.dumps(result))

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
