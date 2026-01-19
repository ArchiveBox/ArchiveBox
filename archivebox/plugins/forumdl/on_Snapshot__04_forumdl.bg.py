#!/usr/bin/env python3
"""
Download forum content from a URL using forum-dl.

Usage: on_Snapshot__04_forumdl.bg.py --url=<url> --snapshot-id=<uuid>
Output: Downloads forum content to $PWD/

Environment variables:
    FORUMDL_ENABLED: Enable forum downloading (default: True)
    FORUMDL_BINARY: Path to forum-dl binary (default: forum-dl)
    FORUMDL_TIMEOUT: Timeout in seconds (x-fallback: TIMEOUT)
    FORUMDL_OUTPUT_FORMAT: Output format (default: jsonl)
    FORUMDL_CHECK_SSL_VALIDITY: Whether to verify SSL certs (x-fallback: CHECK_SSL_VALIDITY)
    FORUMDL_ARGS: Default forum-dl arguments (JSON array)
    FORUMDL_ARGS_EXTRA: Extra arguments to append (JSON array)
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import rich_click as click


# Monkey patch forum-dl for Pydantic v2 compatibility
# forum-dl 0.3.0 uses deprecated json(models_as_dict=False) which doesn't work in Pydantic v2
try:
    from forum_dl.writers.jsonl import JsonlWriter
    from pydantic import BaseModel

    # Check if we're using Pydantic v2 (has model_dump_json)
    if hasattr(BaseModel, 'model_dump_json'):
        # Patch JsonlWriter to use Pydantic v2 API
        original_serialize = JsonlWriter._serialize_entry

        def _patched_serialize_entry(self, entry):
            # Use Pydantic v2's model_dump_json() instead of deprecated json(models_as_dict=False)
            return entry.model_dump_json()

        JsonlWriter._serialize_entry = _patched_serialize_entry
except (ImportError, AttributeError):
    # forum-dl not installed or already compatible
    pass


# Extractor metadata
PLUGIN_NAME = 'forumdl'
BIN_NAME = 'forum-dl'
BIN_PROVIDERS = 'pip,env'
OUTPUT_DIR = '.'


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


def get_binary_shebang(binary_path: str) -> str | None:
    """Return interpreter from shebang line if present (e.g., /path/to/python)."""
    try:
        with open(binary_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            if first_line.startswith('#!'):
                return first_line[2:].strip().split(' ')[0]
    except Exception:
        pass
    return None


def resolve_binary_path(binary: str) -> str | None:
    """Resolve binary to an absolute path if possible."""
    if not binary:
        return None
    if Path(binary).is_file():
        return binary
    return shutil.which(binary)



def save_forum(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Download forum using forum-dl.

    Returns: (success, output_path, error_message)
    """
    # Get config from env (with FORUMDL_ prefix, x-fallback handled by config loader)
    timeout = get_env_int('FORUMDL_TIMEOUT') or get_env_int('TIMEOUT', 3600)
    check_ssl = get_env_bool('FORUMDL_CHECK_SSL_VALIDITY', True) if get_env('FORUMDL_CHECK_SSL_VALIDITY') else get_env_bool('CHECK_SSL_VALIDITY', True)
    forumdl_args = get_env_array('FORUMDL_ARGS', [])
    forumdl_args_extra = get_env_array('FORUMDL_ARGS_EXTRA', [])
    output_format = get_env('FORUMDL_OUTPUT_FORMAT', 'jsonl')

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)

    # Build output filename based on format
    if output_format == 'warc':
        output_file = output_dir / 'forum.warc.gz'
    elif output_format == 'jsonl':
        output_file = output_dir / 'forum.jsonl'
    elif output_format == 'maildir':
        output_file = output_dir / 'forum'  # maildir is a directory
    elif output_format in ('mbox', 'mh', 'mmdf', 'babyl'):
        output_file = output_dir / f'forum.{output_format}'
    else:
        output_file = output_dir / f'forum.{output_format}'

    # Use our Pydantic v2 compatible wrapper if available, otherwise fall back to binary
    wrapper_path = Path(__file__).parent / 'forum-dl-wrapper.py'
    resolved_binary = resolve_binary_path(binary) or binary
    if wrapper_path.exists():
        forumdl_python = get_binary_shebang(resolved_binary) or sys.executable
        cmd = [forumdl_python, str(wrapper_path), *forumdl_args, '-f', output_format, '-o', str(output_file)]
    else:
        cmd = [resolved_binary, *forumdl_args, '-f', output_format, '-o', str(output_file)]

    if not check_ssl:
        cmd.append('--no-check-certificate')

    if forumdl_args_extra:
        cmd.extend(forumdl_args_extra)

    cmd.append(url)

    try:
        print(f'[forumdl] Starting download (timeout={timeout}s)', file=sys.stderr)
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

        # Check if output file was created
        if output_file.exists() and output_file.stat().st_size > 0:
            return True, str(output_file), ''
        else:
            stderr = combined_output

            # These are NOT errors - page simply has no downloadable forum content
            stderr_lower = stderr.lower()
            if 'unsupported url' in stderr_lower:
                return True, None, ''  # Not a forum site - success, no output
            if 'no content' in stderr_lower:
                return True, None, ''  # No forum found - success, no output
            if 'extractornotfounderror' in stderr_lower:
                return True, None, ''  # No forum extractor for this URL - success, no output
            if process.returncode == 0:
                return True, None, ''  # forum-dl exited cleanly, just no forum - success

            # These ARE errors - something went wrong
            if '404' in stderr:
                return False, None, '404 Not Found'
            if '403' in stderr:
                return False, None, '403 Forbidden'
            if 'unable to extract' in stderr_lower:
                return False, None, 'Unable to extract forum info'

            return False, None, f'forum-dl error: {stderr}'

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to download forum from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Download forum content from a URL using forum-dl."""

    output = None
    status = 'failed'
    error = ''

    try:
        # Check if forum-dl is enabled
        if not get_env_bool('FORUMDL_ENABLED', True):
            print('Skipping forum-dl (FORUMDL_ENABLED=False)', file=sys.stderr)
            # Temporary failure (config disabled) - NO JSONL emission
            sys.exit(0)

        # Get binary from environment
        binary = get_env('FORUMDL_BINARY', 'forum-dl')

        # Run extraction
        success, output, error = save_forum(url, binary)

        if success:
            # Success - emit ArchiveResult
            result = {
                'type': 'ArchiveResult',
                'status': 'succeeded',
                'output_str': output or ''
            }
            print(json.dumps(result))
            sys.exit(0)
        else:
            # Transient error - emit NO JSONL
            print(f'ERROR: {error}', file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        # Transient error - emit NO JSONL
        print(f'ERROR: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
