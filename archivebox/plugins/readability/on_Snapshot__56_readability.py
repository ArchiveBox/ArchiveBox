#!/usr/bin/env python3
"""
Extract article content using Mozilla's Readability.

Usage: on_Snapshot__readability.py --url=<url> --snapshot-id=<uuid>
Output: Creates readability/ directory with content.html, content.txt, article.json

Environment variables:
    READABILITY_BINARY: Path to readability-extractor binary
    READABILITY_TIMEOUT: Timeout in seconds (default: 60)
    READABILITY_ARGS: Default Readability arguments (JSON array)
    READABILITY_ARGS_EXTRA: Extra arguments to append (JSON array)
    TIMEOUT: Fallback timeout

Note: Requires readability-extractor from https://github.com/ArchiveBox/readability-extractor
      This extractor looks for HTML source from other extractors (wget, singlefile, dom)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'readability'
BIN_NAME = 'readability-extractor'
BIN_PROVIDERS = 'npm,env'
OUTPUT_DIR = '.'
OUTPUT_FILE = 'content.html'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


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


def find_html_source() -> str | None:
    """Find HTML content from other extractors in the snapshot directory."""
    # Hooks run in snapshot_dir, sibling extractor outputs are in subdirectories
    search_patterns = [
        'singlefile/singlefile.html',
        '*_singlefile/singlefile.html',
        'singlefile/*.html',
        '*_singlefile/*.html',
        'dom/output.html',
        '*_dom/output.html',
        'dom/*.html',
        '*_dom/*.html',
        'wget/**/*.html',
        '*_wget/**/*.html',
        'wget/**/*.htm',
        '*_wget/**/*.htm',
    ]

    for base in (Path.cwd(), Path.cwd().parent):
        for pattern in search_patterns:
            matches = list(base.glob(pattern))
            for match in matches:
                if match.is_file() and match.stat().st_size > 0:
                    return str(match)

    return None


def extract_readability(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Extract article using Readability.

    Returns: (success, output_path, error_message)
    """
    timeout = get_env_int('READABILITY_TIMEOUT') or get_env_int('TIMEOUT', 60)
    readability_args = get_env_array('READABILITY_ARGS', [])
    readability_args_extra = get_env_array('READABILITY_ARGS_EXTRA', [])

    # Find HTML source
    html_source = find_html_source()
    if not html_source:
        return False, None, 'No HTML source found (run singlefile, dom, or wget first)'

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)

    try:
        # Run readability-extractor (outputs JSON by default)
        cmd = [binary, *readability_args, *readability_args_extra, html_source]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, timeout=timeout, text=True)

        if result.stdout:
            sys.stderr.write(result.stdout)
            sys.stderr.flush()

        if result.returncode != 0:
            return False, None, f'readability-extractor failed (exit={result.returncode})'

        # Parse JSON output
        try:
            result_json = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False, None, 'readability-extractor returned invalid JSON'

        # Extract and save content
        # readability-extractor uses camelCase field names (textContent, content)
        text_content = result_json.pop('textContent', result_json.pop('text-content', ''))
        html_content = result_json.pop('content', result_json.pop('html-content', ''))

        if not text_content and not html_content:
            return False, None, 'No content extracted'

        (output_dir / OUTPUT_FILE).write_text(html_content, encoding='utf-8')
        (output_dir / 'content.txt').write_text(text_content, encoding='utf-8')
        (output_dir / 'article.json').write_text(json.dumps(result_json, indent=2), encoding='utf-8')

        return True, OUTPUT_FILE, ''

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to extract article from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Extract article content using Mozilla's Readability."""

    try:
        # Get binary from environment
        binary = get_env('READABILITY_BINARY', 'readability-extractor')

        # Run extraction
        success, output, error = extract_readability(url, binary)

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
