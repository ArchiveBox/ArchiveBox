#!/usr/bin/env python3
"""
Download 3D/CAD asset files from a URL.

Usage: on_Snapshot__caddl.py --url=<url> --snapshot-id=<uuid>
Output: Downloads 3D/CAD files to $PWD/caddl/

Environment variables:
    CADDL_ENABLED: Enable CAD/3D asset extraction (default: True)
    CADDL_TIMEOUT: Timeout in seconds (x-fallback: TIMEOUT)
    CADDL_MAX_SIZE: Maximum file size (default: 750m)
    CADDL_COOKIES_FILE: Path to cookies file (x-fallback: COOKIES_FILE)
    CADDL_CHECK_SSL_VALIDITY: Whether to verify SSL certs (x-fallback: CHECK_SSL_VALIDITY)
    CADDL_USER_AGENT: User agent string (x-fallback: USER_AGENT)
    CADDL_EXTENSIONS: JSON array of file extensions to download
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import rich_click as click
except ImportError:
    import click


# Extractor metadata
PLUGIN_NAME = 'caddl'
BIN_NAME = 'curl'
BIN_PROVIDERS = 'apt,brew,env'
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


def parse_size_limit(size_str: str) -> int:
    """Convert size string like '750m' to bytes."""
    if not size_str:
        return 750 * 1024 * 1024  # Default 750MB

    size_str = size_str.lower().strip()
    multipliers = {'k': 1024, 'm': 1024**2, 'g': 1024**3}

    if size_str[-1] in multipliers:
        try:
            num = float(size_str[:-1])
            return int(num * multipliers[size_str[-1]])
        except ValueError:
            return 750 * 1024 * 1024

    try:
        return int(size_str)
    except ValueError:
        return 750 * 1024 * 1024


SINGLEFILE_DIR = '../singlefile'
DOM_DIR = '../dom'


def get_html_content() -> str | None:
    """Get HTML content from singlefile or dom output."""
    # Try singlefile first
    singlefile_path = Path(SINGLEFILE_DIR)
    if singlefile_path.exists():
        for html_file in singlefile_path.glob('*.html'):
            try:
                return html_file.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                pass

    # Try dom output
    dom_path = Path(DOM_DIR)
    if dom_path.exists():
        for html_file in dom_path.glob('*.html'):
            try:
                return html_file.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                pass

    return None


def find_cad_urls(html: str, base_url: str, extensions: list[str]) -> list[str]:
    """
    Find URLs in HTML that point to 3D/CAD files.

    Returns: List of absolute URLs
    """
    urls = set()

    # Convert extensions to lowercase for matching
    extensions_lower = [ext.lower() for ext in extensions]

    # Find all URLs in href and src attributes
    # Pattern matches: href="..." or src="..."
    url_pattern = r'(?:href|src)=["\']([^"\']+)["\']'

    for match in re.finditer(url_pattern, html, re.IGNORECASE):
        url = match.group(1)

        # Check if URL ends with one of our target extensions
        url_lower = url.lower()
        if any(url_lower.endswith(ext) for ext in extensions_lower):
            # Convert to absolute URL
            absolute_url = urljoin(base_url, url)
            urls.add(absolute_url)

    # Also look for direct URLs in the text (not in tags)
    # Match URLs that end with our extensions
    text_url_pattern = r'https?://[^\s<>"\']+(?:' + '|'.join(re.escape(ext) for ext in extensions_lower) + r')'

    for match in re.finditer(text_url_pattern, html, re.IGNORECASE):
        url = match.group(0)
        urls.add(url)

    return sorted(urls)


def download_file(url: str, output_dir: Path, binary: str, timeout: int,
                  max_size: int, check_ssl: bool, user_agent: str,
                  cookies_file: str) -> tuple[bool, str | None, str]:
    """
    Download a single file using curl.

    Returns: (success, output_path, error_message)
    """
    # Get filename from URL
    parsed = urlparse(url)
    filename = Path(parsed.path).name

    # Sanitize filename
    filename = re.sub(r'[^\w\-_\.]', '_', filename)
    if not filename:
        filename = 'asset.bin'

    output_path = output_dir / filename

    # Avoid overwriting existing files
    counter = 1
    while output_path.exists():
        stem = output_path.stem
        suffix = output_path.suffix
        output_path = output_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    # Build curl command
    cmd = [
        binary,
        '-L',  # Follow redirects
        '--max-time', str(timeout),
        '--max-filesize', str(max_size),
        '-o', str(output_path),
    ]

    if not check_ssl:
        cmd.append('--insecure')

    if user_agent:
        cmd.extend(['-A', user_agent])

    if cookies_file and Path(cookies_file).exists():
        cmd.extend(['-b', cookies_file])

    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 10, text=True)

        if result.returncode == 0 and output_path.exists():
            return True, str(output_path), ''
        else:
            # Clean up partial download
            if output_path.exists():
                output_path.unlink()

            stderr = result.stderr
            if 'Maximum file size exceeded' in stderr:
                return False, None, f'File exceeds max size limit'
            if '404' in stderr or 'Not Found' in stderr:
                return False, None, '404 Not Found'
            if '403' in stderr or 'Forbidden' in stderr:
                return False, None, '403 Forbidden'

            return False, None, f'Download failed: {stderr[:200]}'

    except subprocess.TimeoutExpired:
        if output_path.exists():
            output_path.unlink()
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        if output_path.exists():
            output_path.unlink()
        return False, None, f'{type(e).__name__}: {e}'


def save_cad_assets(url: str, binary: str) -> tuple[bool, list[str], str]:
    """
    Find and download all 3D/CAD assets from a URL.

    Returns: (success, output_paths, error_message)
    """
    # Get config from env
    timeout = get_env_int('CADDL_TIMEOUT') or get_env_int('TIMEOUT', 300)
    check_ssl = get_env_bool('CADDL_CHECK_SSL_VALIDITY', True) if get_env('CADDL_CHECK_SSL_VALIDITY') else get_env_bool('CHECK_SSL_VALIDITY', True)
    max_size_str = get_env('CADDL_MAX_SIZE', '750m')
    max_size = parse_size_limit(max_size_str)
    user_agent = get_env('CADDL_USER_AGENT') or get_env('USER_AGENT', '')
    cookies_file = get_env('CADDL_COOKIES_FILE') or get_env('COOKIES_FILE', '')
    extensions = get_env_array('CADDL_EXTENSIONS', [
        '.blend', '.stl', '.obj', '.step', '.stp',
        '.gltf', '.glb', '.fbx', '.vrm', '.usdz',
        '.dae', '.3ds', '.ply', '.off', '.x3d'
    ])

    # Output directory
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get HTML content from previous extractors
    html = get_html_content()
    if not html:
        # No HTML available - try the URL directly if it looks like a CAD file
        url_lower = url.lower()
        if any(url_lower.endswith(ext) for ext in extensions):
            success, output_path, error = download_file(
                url, output_dir, binary, timeout, max_size,
                check_ssl, user_agent, cookies_file
            )
            if success:
                return True, [output_path], ''
            else:
                return False, [], error
        else:
            # No HTML and URL is not a direct CAD file - nothing to do
            return True, [], ''

    # Find CAD URLs in HTML
    cad_urls = find_cad_urls(html, url, extensions)

    if not cad_urls:
        # No CAD files found - this is not an error, just nothing to download
        return True, [], ''

    # Download each file
    downloaded = []
    errors = []

    for cad_url in cad_urls:
        success, output_path, error = download_file(
            cad_url, output_dir, binary, timeout, max_size,
            check_ssl, user_agent, cookies_file
        )

        if success and output_path:
            downloaded.append(output_path)
        elif error:
            errors.append(f'{cad_url}: {error}')

    if downloaded:
        return True, downloaded, ''
    elif errors:
        return False, [], '; '.join(errors[:3])  # Return first 3 errors
    else:
        return True, [], ''


@click.command()
@click.option('--url', required=True, help='URL to extract CAD assets from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Download 3D/CAD assets from a URL."""

    try:
        # Check if caddl is enabled
        if not get_env_bool('CADDL_ENABLED', True):
            print('Skipping caddl (CADDL_ENABLED=False)', file=sys.stderr)
            sys.exit(0)

        # Get binary from environment
        binary = get_env('CADDL_BINARY', 'curl')

        # Run extraction
        success, outputs, error = save_cad_assets(url, binary)

        if success and outputs:
            # Success - emit ArchiveResult for each downloaded file
            for output in outputs:
                result = {
                    'type': 'ArchiveResult',
                    'status': 'succeeded',
                    'output_str': output
                }
                print(json.dumps(result))
            sys.exit(0)
        elif success and not outputs:
            # Success but no files found - emit success with no output
            result = {
                'type': 'ArchiveResult',
                'status': 'succeeded',
                'output_str': ''
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
