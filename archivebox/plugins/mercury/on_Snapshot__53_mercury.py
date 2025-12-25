#!/usr/bin/env python3
"""
Extract article content using Postlight's Mercury Parser.

Usage: on_Snapshot__mercury.py --url=<url> --snapshot-id=<uuid>
Output: Creates mercury/ directory with content.html, content.txt, article.json

Environment variables:
    MERCURY_BINARY: Path to postlight-parser binary
    TIMEOUT: Timeout in seconds (default: 60)

Note: Requires postlight-parser: npm install -g @postlight/parser
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'mercury'
BIN_NAME = 'postlight-parser'
BIN_PROVIDERS = 'npm,env'
OUTPUT_DIR = 'mercury'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def find_mercury() -> str | None:
    """Find postlight-parser binary."""
    mercury = get_env('MERCURY_BINARY')
    if mercury and os.path.isfile(mercury):
        return mercury

    for name in ['postlight-parser']:
        binary = shutil.which(name)
        if binary:
            return binary

    return None


def get_version(binary: str) -> str:
    """Get postlight-parser version."""
    try:
        result = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
        return result.stdout.strip()[:64]
    except Exception:
        return ''


def extract_mercury(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Extract article using Mercury Parser.

    Returns: (success, output_path, error_message)
    """
    timeout = get_env_int('TIMEOUT', 60)

    # Create output directory
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(exist_ok=True)

    try:
        # Get text version
        cmd_text = [binary, url, '--format=text']
        result_text = subprocess.run(cmd_text, capture_output=True, timeout=timeout)

        if result_text.returncode != 0:
            stderr = result_text.stderr.decode('utf-8', errors='replace')
            return False, None, f'postlight-parser failed: {stderr[:200]}'

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
        cmd_html = [binary, url, '--format=html']
        result_html = subprocess.run(cmd_html, capture_output=True, timeout=timeout)

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

    start_ts = datetime.now(timezone.utc)
    version = ''
    output = None
    status = 'failed'
    error = ''
    binary = None

    try:
        # Find binary
        binary = find_mercury()
        if not binary:
            print(f'ERROR: postlight-parser binary not found', file=sys.stderr)
            print(f'DEPENDENCY_NEEDED={BIN_NAME}', file=sys.stderr)
            print(f'BIN_PROVIDERS={BIN_PROVIDERS}', file=sys.stderr)
            sys.exit(1)

        version = get_version(binary)

        # Run extraction
        success, output, error = extract_mercury(url, binary)
        status = 'succeeded' if success else 'failed'

        if success:
            text_file = Path(output) / 'content.txt'
            html_file = Path(output) / 'content.html'
            text_len = text_file.stat().st_size if text_file.exists() else 0
            html_len = html_file.stat().st_size if html_file.exists() else 0
            print(f'Mercury extracted: {text_len} chars text, {html_len} chars HTML')

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
        print(f'CMD={binary} {url}')
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
