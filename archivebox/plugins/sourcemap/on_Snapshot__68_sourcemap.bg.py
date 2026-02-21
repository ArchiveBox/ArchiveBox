#!/usr/bin/env python3
"""
Download JavaScript sourcemap (.js.map) files for any compiled/minified JS assets used in archived pages.

Sourcemaps allow minified/compiled JavaScript to be traced back to the original
source code, making archived pages much more useful for developers.

Usage: on_Snapshot__68_sourcemap.bg.py --url=<url> --snapshot-id=<uuid>
Output: Writes <name>.js.map files to $PWD/sourcemap/

Environment variables:
    SOURCEMAP_TIMEOUT:   Timeout in seconds (default: 60)
    SOURCEMAP_USER_AGENT: User agent string
    SOURCEMAP_MAX_FILES: Max sourcemap files to download per snapshot (default: 50)

    # Fallback to ARCHIVING_CONFIG values if SOURCEMAP_* not set:
    TIMEOUT:    Fallback timeout
    USER_AGENT: Fallback user agent

Note: This extractor uses the 'requests' library which is bundled with ArchiveBox.
      It can run standalone if requests is installed: pip install requests
"""

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'sourcemap'
OUTPUT_DIR = 'sourcemap'

# Regex to find sourceMappingURL in JS content
# Handles both: //# sourceMappingURL=foo.js.map  and  /*# sourceMappingURL=foo.js.map */
SOURCEMAP_URL_RE = re.compile(
    r'(?://|/\*)#\s*sourceMappingURL=([^\s*]+)',
    re.MULTILINE,
)

# Regex to find <script src="..."> tags in HTML
SCRIPT_SRC_RE = re.compile(
    r'<script[^>]+src=["\']([^"\']+\.js(?:[?#][^"\']*)?)["\']',
    re.IGNORECASE,
)

# Regex to find X-SourceMap or SourceMap response headers (checked after fetching)
# Also handles data URIs embedded directly in sourceMappingURL
DATA_URI_RE = re.compile(r'^data:', re.IGNORECASE)


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def log_info(msg: str) -> None:
    print(f'[sourcemap] {msg}', file=sys.stderr)


def log_error(msg: str) -> None:
    print(f'ERROR [sourcemap] {msg}', file=sys.stderr)


def find_sourcemap_urls_in_js(js_content: str, js_url: str) -> list[str]:
    """Extract sourcemap URLs referenced inside a JS file."""
    urls = []
    for match in SOURCEMAP_URL_RE.finditer(js_content):
        raw = match.group(1).strip()
        # Skip data URIs (inline sourcemaps - already embedded)
        if DATA_URI_RE.match(raw):
            continue
        resolved = urljoin(js_url, raw)
        urls.append(resolved)
    return urls


def safe_filename(url: str) -> str:
    """Convert a URL to a safe local filename inside the output dir."""
    parsed = urlparse(url)
    # Use path component, strip leading slash, replace path separators
    path = parsed.path.lstrip('/')
    # Replace any remaining slashes with underscores to flatten
    path = path.replace('/', '_')
    if not path:
        path = 'sourcemap.js.map'
    # Ensure it ends with .map for clarity
    if not path.endswith('.map'):
        path = path + '.map'
    return path


def get_sourcemaps(url: str) -> tuple[bool, list[str], str]:
    """
    Fetch the page at url, discover all JS assets, fetch each JS file,
    find sourceMappingURL references, and download the .map files.

    Returns: (success, list_of_downloaded_files, error_message)
    """
    try:
        import requests
    except ImportError:
        return False, [], 'requests library not installed'

    timeout = get_env_int('SOURCEMAP_TIMEOUT') or get_env_int('TIMEOUT', 60)
    user_agent = get_env('SOURCEMAP_USER_AGENT') or get_env('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)')
    max_files = get_env_int('SOURCEMAP_MAX_FILES', 50)
    headers = {'User-Agent': user_agent}

    session = requests.Session()
    session.headers.update(headers)

    # Step 1: Fetch the HTML page to find script tags
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        html_content = response.text
    except Exception as e:
        return False, [], f'Failed to fetch page: {e}'

    # Step 2: Find all <script src="..."> URLs
    js_urls: list[str] = []
    for match in SCRIPT_SRC_RE.finditer(html_content):
        js_url = urljoin(url, match.group(1))
        # Strip query/fragment for the JS file itself
        js_url_clean = js_url.split('?')[0].split('#')[0]
        if js_url_clean not in js_urls:
            js_urls.append(js_url_clean)

    if not js_urls:
        return False, [], 'No JavaScript files found in page'

    log_info(f'Found {len(js_urls)} JS file(s) to check for sourcemaps')

    # Step 3: Fetch each JS file and look for sourceMappingURL
    sourcemap_urls: list[str] = []
    for js_url in js_urls:
        try:
            js_response = session.get(js_url, timeout=timeout)
            if not js_response.ok:
                continue

            # Check X-SourceMap or SourceMap response header
            for header_name in ('X-SourceMap', 'SourceMap'):
                header_val = js_response.headers.get(header_name, '').strip()
                if header_val and not DATA_URI_RE.match(header_val):
                    resolved = urljoin(js_url, header_val)
                    if resolved not in sourcemap_urls:
                        sourcemap_urls.append(resolved)

            # Check sourceMappingURL comment in JS body
            for map_url in find_sourcemap_urls_in_js(js_response.text, js_url):
                if map_url not in sourcemap_urls:
                    sourcemap_urls.append(map_url)

        except Exception as e:
            log_info(f'Skipping {js_url}: {e}')
            continue

    if not sourcemap_urls:
        return False, [], 'No sourcemap references found in JS files'

    # Respect max_files limit
    if len(sourcemap_urls) > max_files:
        log_info(f'Found {len(sourcemap_urls)} sourcemaps, limiting to {max_files}')
        sourcemap_urls = sourcemap_urls[:max_files]

    log_info(f'Downloading {len(sourcemap_urls)} sourcemap file(s)')

    # Step 4: Create output directory and download each .map file
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)

    downloaded: list[str] = []
    for map_url in sourcemap_urls:
        try:
            map_response = session.get(map_url, timeout=timeout)
            if not map_response.ok:
                log_info(f'Failed to fetch {map_url}: HTTP {map_response.status_code}')
                continue

            filename = safe_filename(map_url)
            dest = output_path / filename
            # Avoid overwriting if multiple JS files reference the same map name
            if dest.exists():
                stem = dest.stem
                suffix = dest.suffix
                dest = output_path / f'{stem}_{len(downloaded)}{suffix}'

            dest.write_bytes(map_response.content)
            downloaded.append(str(dest))
            log_info(f'Saved {map_url} → {dest}')

        except Exception as e:
            log_info(f'Failed to download {map_url}: {e}')
            continue

    if downloaded:
        return True, downloaded, ''
    return False, [], 'Failed to download any sourcemap files'


@click.command()
@click.option('--url', required=True, help='URL of page to extract sourcemaps from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Download JavaScript sourcemap (.js.map) files for archived pages."""

    downloaded: list[str] = []
    status = 'failed'
    error = ''

    try:
        success, downloaded, error = get_sourcemaps(url)
        if success:
            status = 'succeeded'
        else:
            status = 'failed'
    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    if error:
        print(f'ERROR: {error}', file=sys.stderr)

    output_str = ', '.join(downloaded) if downloaded else (error or 'no sourcemaps found')

    result = {
        'type': 'ArchiveResult',
        'status': status,
        'output_str': output_str,
    }
    print(json.dumps(result))

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
