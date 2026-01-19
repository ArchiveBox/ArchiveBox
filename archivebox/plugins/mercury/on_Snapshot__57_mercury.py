#!/usr/bin/env python3
"""
Extract article content using Postlight's Mercury Parser.

Usage: on_Snapshot__mercury.py --url=<url> --snapshot-id=<uuid>
Output: Creates mercury/ directory with content.html, content.txt, article.json

Environment variables:
    MERCURY_BINARY: Path to postlight-parser binary
    MERCURY_TIMEOUT: Timeout in seconds (default: 60)
    MERCURY_ARGS: Default Mercury arguments (JSON array)
    MERCURY_ARGS_EXTRA: Extra arguments to append (JSON array)
    TIMEOUT: Fallback timeout

Note: Requires postlight-parser: npm install -g @postlight/parser
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'mercury'
BIN_NAME = 'postlight-parser'
BIN_PROVIDERS = 'npm,env'
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


def extract_mercury(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Extract article using Mercury Parser.

    Returns: (success, output_path, error_message)
    """
    timeout = get_env_int('MERCURY_TIMEOUT') or get_env_int('TIMEOUT', 60)
    mercury_args = get_env_array('MERCURY_ARGS', [])
    mercury_args_extra = get_env_array('MERCURY_ARGS_EXTRA', [])

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)

    try:
        # Get text version
        cmd_text = [binary, *mercury_args, *mercury_args_extra, url, '--format=text']
        result_text = subprocess.run(cmd_text, stdout=subprocess.PIPE, timeout=timeout, text=True)
        if result_text.stdout:
            sys.stderr.write(result_text.stdout)
            sys.stderr.flush()

        if result_text.returncode != 0:
            return False, None, f'postlight-parser failed (exit={result_text.returncode})'

        try:
            text_json = json.loads(result_text.stdout)
        except json.JSONDecodeError:
            return False, None, 'postlight-parser returned invalid JSON'

        if text_json.get('failed'):
            return False, None, 'Mercury was not able to extract article'

        # Save text content
        text_content = text_json.get('content', '')
        (output_dir / 'content.txt').write_text(text_content, encoding='utf-8')

        # Get HTML version
        cmd_html = [binary, *mercury_args, *mercury_args_extra, url, '--format=html']
        result_html = subprocess.run(cmd_html, stdout=subprocess.PIPE, timeout=timeout, text=True)
        if result_html.stdout:
            sys.stderr.write(result_html.stdout)
            sys.stderr.flush()

        try:
            html_json = json.loads(result_html.stdout)
        except json.JSONDecodeError:
            html_json = {}

        # Save HTML content and metadata
        html_content = html_json.pop('content', '')
        (output_dir / 'content.html').write_text(html_content, encoding='utf-8')

        # Save article metadata
        metadata = {k: v for k, v in text_json.items() if k != 'content'}
        (output_dir / 'article.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')

        return True, OUTPUT_DIR, ''

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to extract article from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Extract article content using Postlight's Mercury Parser."""

    try:
        # Check if mercury extraction is enabled
        if not get_env_bool('MERCURY_ENABLED', True):
            print('Skipping mercury (MERCURY_ENABLED=False)', file=sys.stderr)
            # Temporary failure (config disabled) - NO JSONL emission
            sys.exit(0)

        # Get binary from environment
        binary = get_env('MERCURY_BINARY', 'postlight-parser')

        # Run extraction
        success, output, error = extract_mercury(url, binary)

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
