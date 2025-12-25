#!/usr/bin/env python3
"""
Extract article content using Mozilla's Readability.

Usage: on_Snapshot__readability.py --url=<url> --snapshot-id=<uuid>
Output: Creates readability/ directory with content.html, content.txt, article.json

Environment variables:
    READABILITY_BINARY: Path to readability-extractor binary
    TIMEOUT: Timeout in seconds (default: 60)

Note: Requires readability-extractor from https://github.com/ArchiveBox/readability-extractor
      This extractor looks for HTML source from other extractors (wget, singlefile, dom)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'readability'
BIN_NAME = 'readability-extractor'
BIN_PROVIDERS = 'npm,env'
OUTPUT_DIR = '.'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def find_readability() -> str | None:
    """Find readability-extractor binary."""
    readability = get_env('READABILITY_BINARY')
    if readability and os.path.isfile(readability):
        return readability

    for name in ['readability-extractor']:
        binary = shutil.which(name)
        if binary:
            return binary

    return None


def get_version(binary: str) -> str:
    """Get readability-extractor version."""
    try:
        result = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
        return result.stdout.strip()[:64]
    except Exception:
        return ''


def find_html_source() -> str | None:
    """Find HTML content from other extractors in the snapshot directory."""
    # Hooks run in snapshot_dir, sibling extractor outputs are in subdirectories
    search_patterns = [
        'singlefile/singlefile.html',
        'singlefile/*.html',
        'dom/output.html',
        'dom/*.html',
        'wget/**/*.html',
        'wget/**/*.htm',
    ]

    cwd = Path.cwd()
    for pattern in search_patterns:
        matches = list(cwd.glob(pattern))
        for match in matches:
            if match.is_file() and match.stat().st_size > 0:
                return str(match)

    return None


def extract_readability(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Extract article using Readability.

    Returns: (success, output_path, error_message)
    """
    timeout = get_env_int('TIMEOUT', 60)

    # Find HTML source
    html_source = find_html_source()
    if not html_source:
        return False, None, 'No HTML source found (run singlefile, dom, or wget first)'

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)

    try:
        # Run readability-extractor (outputs JSON by default)
        cmd = [binary, html_source]
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)

        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='replace')
            return False, None, f'readability-extractor failed: {stderr[:200]}'

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

        (output_dir / 'content.html').write_text(html_content, encoding='utf-8')
        (output_dir / 'content.txt').write_text(text_content, encoding='utf-8')
        (output_dir / 'article.json').write_text(json.dumps(result_json, indent=2), encoding='utf-8')

        return True, OUTPUT_DIR, ''

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to extract article from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Extract article content using Mozilla's Readability."""

    start_ts = datetime.now(timezone.utc)
    version = ''
    output = None
    status = 'failed'
    error = ''
    binary = None

    try:
        # Find binary
        binary = find_readability()
        if not binary:
            print(f'ERROR: readability-extractor binary not found', file=sys.stderr)
            print(f'DEPENDENCY_NEEDED={BIN_NAME}', file=sys.stderr)
            print(f'BIN_PROVIDERS={BIN_PROVIDERS}', file=sys.stderr)
            sys.exit(1)

        version = get_version(binary)

        # Run extraction
        success, output, error = extract_readability(url, binary)
        status = 'succeeded' if success else 'failed'

        if success:
            text_file = Path(output) / 'content.txt'
            html_file = Path(output) / 'content.html'
            text_len = text_file.stat().st_size if text_file.exists() else 0
            html_len = html_file.stat().st_size if html_file.exists() else 0
            print(f'Readability extracted: {text_len} chars text, {html_len} chars HTML')

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    # Print results
    end_ts = datetime.now(timezone.utc)
    duration = (end_ts - start_ts).total_seconds()

    print(f'START_TS={start_ts.isoformat()}')
    print(f'END_TS={end_ts.isoformat()}')
    print(f'DURATION={duration:.2f}')
    if binary:
        print(f'CMD={binary} <html>')
    if version:
        print(f'VERSION={version}')
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
        'cmd_version': version,
        'output': output,
        'error': error or None,
    }
    print(f'RESULT_JSON={json.dumps(result_json)}')

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
