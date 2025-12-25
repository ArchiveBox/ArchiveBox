#!/usr/bin/env python3
"""
Download static files (PDFs, images, archives, etc.) directly.

This extractor runs AFTER chrome_session and checks the Content-Type header
from chrome_session/response_headers.json to determine if the URL points to
a static file that should be downloaded directly.

Other extractors check for the presence of this extractor's output directory
to know if they should skip (since Chrome-based extractors can't meaningfully
process static files like PDFs, images, etc.).

Usage: on_Snapshot__21_staticfile.py --url=<url> --snapshot-id=<uuid>
Output: Downloads file to staticfile/<filename>

Environment variables:
    STATICFILE_TIMEOUT: Timeout in seconds (default: 300)
    STATICFILE_MAX_SIZE: Maximum file size in bytes (default: 1GB)
    USER_AGENT: User agent string (optional)
    CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: True)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote

import rich_click as click

# Extractor metadata
EXTRACTOR_NAME = 'staticfile'
OUTPUT_DIR = 'staticfile'
CHROME_SESSION_DIR = 'chrome_session'

# Content-Types that indicate static files
# These can't be meaningfully processed by Chrome-based extractors
STATIC_CONTENT_TYPES = {
    # Documents
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/rtf',
    'application/epub+zip',
    # Images
    'image/png',
    'image/jpeg',
    'image/gif',
    'image/webp',
    'image/svg+xml',
    'image/x-icon',
    'image/bmp',
    'image/tiff',
    'image/avif',
    'image/heic',
    'image/heif',
    # Audio
    'audio/mpeg',
    'audio/mp3',
    'audio/wav',
    'audio/flac',
    'audio/aac',
    'audio/ogg',
    'audio/webm',
    'audio/m4a',
    'audio/opus',
    # Video
    'video/mp4',
    'video/webm',
    'video/x-matroska',
    'video/avi',
    'video/quicktime',
    'video/x-ms-wmv',
    'video/x-flv',
    # Archives
    'application/zip',
    'application/x-tar',
    'application/gzip',
    'application/x-bzip2',
    'application/x-xz',
    'application/x-7z-compressed',
    'application/x-rar-compressed',
    'application/vnd.rar',
    # Data
    'application/json',
    'application/xml',
    'text/csv',
    'text/xml',
    'application/x-yaml',
    # Executables/Binaries
    'application/octet-stream',  # Generic binary
    'application/x-executable',
    'application/x-msdos-program',
    'application/x-apple-diskimage',
    'application/vnd.debian.binary-package',
    'application/x-rpm',
    # Other
    'application/x-bittorrent',
    'application/wasm',
}

# Also check Content-Type prefixes for categories
STATIC_CONTENT_TYPE_PREFIXES = (
    'image/',
    'audio/',
    'video/',
    'application/zip',
    'application/x-',
)


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


def get_content_type_from_chrome_session() -> str | None:
    """Read Content-Type from chrome_session's response headers."""
    headers_file = Path(CHROME_SESSION_DIR) / 'response_headers.json'
    if not headers_file.exists():
        return None

    try:
        with open(headers_file) as f:
            headers = json.load(f)
        # Headers might be nested or flat depending on chrome_session format
        content_type = headers.get('content-type') or headers.get('Content-Type') or ''
        # Strip charset and other parameters
        return content_type.split(';')[0].strip().lower()
    except Exception:
        return None


def is_static_content_type(content_type: str) -> bool:
    """Check if Content-Type indicates a static file."""
    if not content_type:
        return False

    # Check exact match
    if content_type in STATIC_CONTENT_TYPES:
        return True

    # Check prefixes
    for prefix in STATIC_CONTENT_TYPE_PREFIXES:
        if content_type.startswith(prefix):
            return True

    return False


def get_filename_from_url(url: str) -> str:
    """Extract filename from URL."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    filename = path.split('/')[-1] or 'downloaded_file'

    # Sanitize filename
    filename = filename.replace('/', '_').replace('\\', '_')
    if len(filename) > 200:
        filename = filename[:200]

    return filename


def download_file(url: str) -> tuple[bool, str | None, str]:
    """
    Download a static file.

    Returns: (success, output_path, error_message)
    """
    import requests

    timeout = get_env_int('STATICFILE_TIMEOUT', 300)
    max_size = get_env_int('STATICFILE_MAX_SIZE', 1024 * 1024 * 1024)  # 1GB default
    user_agent = get_env('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)')
    check_ssl = get_env_bool('CHECK_SSL_VALIDITY', True)

    headers = {'User-Agent': user_agent}

    try:
        # Stream download to handle large files
        response = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            stream=True,
            verify=check_ssl,
            allow_redirects=True,
        )
        response.raise_for_status()

        # Check content length if available
        content_length = response.headers.get('content-length')
        if content_length and int(content_length) > max_size:
            return False, None, f'File too large: {int(content_length)} bytes > {max_size} max'

        # Create output directory
        output_dir = Path(OUTPUT_DIR)
        output_dir.mkdir(exist_ok=True)

        # Determine filename
        filename = get_filename_from_url(url)

        # Check content-disposition header for better filename
        content_disp = response.headers.get('content-disposition', '')
        if 'filename=' in content_disp:
            import re
            match = re.search(r'filename[*]?=["\']?([^"\';\n]+)', content_disp)
            if match:
                filename = match.group(1).strip()

        output_path = output_dir / filename

        # Download in chunks
        downloaded_size = 0
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    downloaded_size += len(chunk)
                    if downloaded_size > max_size:
                        f.close()
                        output_path.unlink()
                        return False, None, f'File too large: exceeded {max_size} bytes'
                    f.write(chunk)

        return True, str(output_path), ''

    except requests.exceptions.Timeout:
        return False, None, f'Timed out after {timeout} seconds'
    except requests.exceptions.SSLError as e:
        return False, None, f'SSL error: {e}'
    except requests.exceptions.RequestException as e:
        return False, None, f'Download failed: {e}'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to download')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Download static files based on Content-Type from chrome_session."""

    start_ts = datetime.now(timezone.utc)
    output = None
    status = 'failed'
    error = ''

    # Check Content-Type from chrome_session's response headers
    content_type = get_content_type_from_chrome_session()

    # If chrome_session didn't run or no Content-Type, skip
    if not content_type:
        print(f'No Content-Type found (chrome_session may not have run)')
        print(f'START_TS={start_ts.isoformat()}')
        print(f'END_TS={datetime.now(timezone.utc).isoformat()}')
        print(f'STATUS=skipped')
        print(f'RESULT_JSON={json.dumps({"extractor": EXTRACTOR_NAME, "status": "skipped", "url": url, "snapshot_id": snapshot_id})}')
        sys.exit(0)  # Permanent skip - can't determine content type

    # If not a static file type, skip (this is the normal case for HTML pages)
    if not is_static_content_type(content_type):
        print(f'Not a static file (Content-Type: {content_type})')
        print(f'START_TS={start_ts.isoformat()}')
        print(f'END_TS={datetime.now(timezone.utc).isoformat()}')
        print(f'STATUS=skipped')
        print(f'RESULT_JSON={json.dumps({"extractor": EXTRACTOR_NAME, "status": "skipped", "url": url, "snapshot_id": snapshot_id, "content_type": content_type})}')
        sys.exit(0)  # Permanent skip - not a static file

    try:
        # Download the file
        print(f'Static file detected (Content-Type: {content_type}), downloading...')
        success, output, error = download_file(url)
        status = 'succeeded' if success else 'failed'

        if success and output:
            size = Path(output).stat().st_size
            print(f'Static file downloaded ({size} bytes): {output}')

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
        'content_type': content_type,
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
